"""Denied commands in /respond (B6): the author is told the form that runs, denials are recorded redacted and kept
across the retry, shown apart from verification gaps, and a result without them still parses."""

import json

from review_harness import respond as RS
from review_harness.providers import claude_code as CC
from review_harness.providers.base import Completion, Provider


def cli_result(denials=None, **extra):
    data = {"type": "result", "is_error": False, "structured_output": {"ok": True}, "usage": {}}
    if denials is not None:
        data["permission_denials"] = denials
    return json.dumps({**data, **extra})


def test_denials_are_read_from_the_cli_result_and_tolerate_missing_fields():
    c = CC.parse_output(cli_result([
        {"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "mkdir -p /tmp/sim && cat > /tmp/sim/s.py"}},
        {"tool_name": "Write", "tool_input": {"file_path": "/etc/passwd"}},
        {"tool_name": "Bash"},                                       # no input
        "not a dict", 7]))
    assert c.denials == [{"tool": "Bash", "command": "mkdir -p *** && cat > ***"},
                         {"tool": "Write", "command": "***"}, {"tool": "Bash", "command": ""}]
    assert CC.parse_output(cli_result()).denials == []               # field absent (older CLI, Codex)
    assert CC.parse_output(cli_result("oops")).denials == []          # malformed
    assert Completion("x").denials == []


def test_secrets_are_masked_before_cutting():
    tok = "ghp_" + "A" * 36
    long_cmd = "echo " + "x " * 150 + tok                            # the token sits past the cut
    out = CC.redact(long_cmd)
    assert len(out) <= CC.DENIAL_LIMIT and "ghp_" not in out
    for secret, kept in ((f"GITHUB_TOKEN={tok} git push", "GITHUB_TOKEN=***"),
                         ("curl -H 'Authorization: Bearer abcdefgh12345678' x", "Authorization: ***"),
                         ("ANTHROPIC_API_KEY=sk-ant-abcdefghijklmnopqrstuv python x.py", "ANTHROPIC_API_KEY=***"),
                         ("export SLACK=xoxb-1234567890-abcdefghij", "SLACK=***"),
                         ("aws s3 ls # AKIAABCDEFGHIJKLMNOP", "aws s3 ls")):
        r = CC.redact(secret)
        assert kept in r, (secret, r)
        assert not any(s in r for s in ("ghp_A", "abcdefgh12345678", "sk-ant-", "xoxb-1234", "AKIAABCD")), r
    assert CC.redact("python -I /tmp/check/run.py") == "python -I /tmp/check/run.py"   # ordinary commands intact
    assert CC.redact("python   x.py\n  -v") == "python x.py -v"


def test_the_respond_prompt_names_the_form_that_runs():
    hint = CC.command_hint("respond", None)
    assert "/tmp" in hint and "Write tool" in hint and "as one command" in hint
    assert "don't repackage it" in hint and "`blocked`" in hint
    assert "/tmp" not in CC.command_hint("review", None)                # reviewers are not told to write files


class DenyingAuthor(Provider):
    """First answer is invalid; both attempts report a denial."""
    model = "fake"

    def __init__(self, work, replies):
        self.work, self.replies = work, list(replies)

    def complete(self, system, messages, max_output_tokens):
        (self.work / "x.py").write_text("x = 2\n")
        n = len(self.replies)
        return Completion(self.replies.pop(0), 1, 1, [{"tool": "Bash", "command": f"python - <<'EOF' attempt {n}"}])


def test_denials_survive_the_retry_and_are_shown_apart_from_gaps(tmp_path):
    from test_review_harness import CFG, ROOT, answer, env_with, finding, resp_json, scratch_repo
    work = scratch_repo(tmp_path)
    env = env_with([finding(id="F1"), finding(id="F2")])
    good = json.dumps(resp_json([answer("F1"),                                      # recovered: ran another way
                                 answer("F2", method="read", outcome="blocked", detail="sketch run denied")]))
    out = RS.respond(ROOT, CFG, DenyingAuthor(work, ["{not json", good]), work, env, "2026-11-01-pr7-gpt.json", 7,
                     "main", "respond/pr7-x")
    assert out["status"] == "done" and [d["command"] for d in out["denials"]] == [
        "python - <<'EOF' attempt 2", "python - <<'EOF' attempt 1"]
    s = out["summary"]
    assert "**Denied commands (2)**" in s and "`python - <<'EOF' attempt 1`" in s
    gaps = s.split("Verification gaps (1)")[1].split("**Denied commands")[0]
    assert "F2 (accept)" in gaps and "F1 (accept)" not in gaps                  # a recovered denial is not a gap


def test_no_denials_no_note_and_long_lists_are_cut():
    resp = resp_json_simple()
    env = {"meta": {"model": "m"}, "review": {"verdict": "approve", "summary": "s", "findings": []}}
    assert "Denied commands" not in RS.render_summary(resp, env, "r.json", [], [], 1, "m")
    many = [{"tool": "Bash", "command": f"c{i}"} for i in range(13)]
    s = RS.render_summary(resp, env, "r.json", [], [], 1, "m", denials=many)
    assert "**Denied commands (13)**" in s and "`c9`" in s and "`c10`" not in s and "…and 3 more" in s
    weird = RS.render_summary(resp, env, "r.json", [], [], 1, "m", denials=[{"tool": "Bash", "command": "a`b"}])
    assert "`a'b`" in weird                                                     # no broken code span


def resp_json_simple():
    return {"schema_version": 1, "summary": "s", "tests": {"ran": True, "passed": True, "detail": "ok"},
            "responses": [{"finding_id": "F1", "decision": "accept", "reason": "r", "changes": "x.py",
                           "verification": {"method": "ran", "outcome": "passed", "detail": "pytest"}}]}


# ---- GPT Sol's review of #10 ------------------------------------------------------------------------------------------

import pytest  # noqa: E402

FAKE = "hunter2"           # synthetic credentials only


@pytest.mark.parametrize("cmd", [
    f'curl -H "Authorization: Basic dXNlcjp{FAKE}" https://x.io',
    f"curl -u alice:{FAKE} https://x.io",
    f"curl --user alice:{FAKE} https://x.io",
    f'mysql --password "correct horse {FAKE}" db',
    f"mysql --password={FAKE} db",
    f"mysql -p{FAKE} db",
    f"git clone https://alice:{FAKE}@github.com/o/r",
    f"psql postgres://u:{FAKE}@db/x",
    f"curl 'https://x.io/api?token={FAKE}'",
    f"curl --data 'pw={FAKE}' https://x.io",
    f"curl --header 'X-Api-Key: {FAKE}' https://x.io",
    f'python -c "import os; os.environ[\'K\']=\'{FAKE}\'"',
    f"cat > /tmp/s.py <<'EOF'\nPASSWORD = '{FAKE}'\nEOF",
])
def test_credentials_in_denied_commands_never_survive(cmd):
    out = CC.safe_command(cmd)
    assert FAKE not in out and "dXNlcj" not in out, out
    assert len(out) <= CC.DENIAL_LIMIT


@pytest.mark.parametrize("cmd, expect", [
    ("python -I /tmp/check/run.py", "python -I ***"),
    ("python -m pytest -q 2>&1 | tail -5", "python -m *** -q 2>&1 | tail -5"),
    ("mkdir -p /tmp/sim && cat > /tmp/sim/sim.py <<'EOF'\nimport os\nprint(1)\nEOF",
     "mkdir -p *** && cat > *** <<… (+3 more lines)"),
    ("git clone https://github.com/o/r", "git *** ***"),
    ('echo "unbalanced', "(command not shown: it could not be parsed safely)"),
    ("python - <<'EOF'\nx\nEOF", "python - <<… (+2 more lines)"),
])
def test_the_shape_survives_and_values_do_not(cmd, expect):
    """What B6 needs from a denial: which programs, flags and shell forms (chains, redirects, heredocs) were used."""
    assert CC.safe_command(cmd) == expect


def test_denials_are_kept_when_the_cli_ends_in_an_error():
    raw = cli_result([{"tool_name": "Bash", "tool_input": {"command": "python - <<'EOF'\nx\nEOF"}}],
                     is_error=True, subtype="error_max_turns")
    with pytest.raises(CC.CLIError) as e:
        CC.parse_output(raw)
    assert e.value.denials == [{"tool": "Bash", "command": "python - <<… (+2 more lines)"}]


def test_the_provider_keeps_denials_from_failed_attempts(monkeypatch):
    import subprocess

    class Proc:
        def __init__(self, out):
            self.stdout, self.stderr, self.returncode = out, "", 0
    outs = [cli_result([{"tool_name": "Bash", "tool_input": {"command": "mkdir -p /tmp/a"}}], is_error=True),
            cli_result([{"tool_name": "Bash", "tool_input": {"command": "cat > /tmp/a/b"}}])]
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")
    p = CC.ClaudeCodeProvider({"model": "m", "secret": "CLAUDE_CODE_OAUTH_TOKEN"},
                              run=lambda *a, **k: Proc(outs.pop(0)), mode="respond")
    with pytest.raises(CC.CLIError):
        p.complete("s", [{"role": "user", "content": "u"}], 100)
    p.complete("s", [{"role": "user", "content": "u"}], 100)
    assert [d["command"] for d in p.denials] == ["mkdir -p ***", "cat > ***"]


def test_a_failed_response_still_reports_its_denials(tmp_path, monkeypatch):
    """Final invalid answer: main exits 2 before writing the record, so the failure message carries the denials."""
    from test_review_harness import env_with, finding, scratch_repo
    (tmp_path / "w").mkdir()
    work = scratch_repo(tmp_path / "w")
    review_file = tmp_path / "2026-11-01-pr7-gpt.json"
    review_file.write_text(json.dumps(env_with([finding(id="F1")])))

    class Bad:
        model, on_step = "fake", None

        def __init__(self, *a, **k):
            self.denials = []

        def complete(self, system, messages, max_output_tokens):
            d = [{"tool": "Bash", "command": "python - <<… (+2 more lines)"}]
            self.denials += d
            return Completion("{not json", 1, 1, d)
    monkeypatch.setattr(CC, "ClaudeCodeProvider", Bad)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "x")
    monkeypatch.setattr("review_harness.progress.Progress.start", lambda self: None)
    monkeypatch.setattr("review_harness.progress.Progress.finish", lambda self, ok, msg: None)
    err = tmp_path / "err.txt"
    code = RS.main(["--work-dir", str(work), "--review-file", str(review_file), "--pr", "7", "--fixed-in", "b",
                    "--summary-out", str(tmp_path / "s.md"), "--error-file", str(err), "--author", "claude"])
    assert code == 2
    msg = err.read_text()
    assert "failed validation" in msg and "Denied commands (2): Bash: python - <<… (+2 more lines)" in msg

    class Crash(Bad):
        def complete(self, system, messages, max_output_tokens):
            self.denials += [{"tool": "Bash", "command": "mkdir -p /tmp/a"}]
            raise CC.CLIError("Claude Code reported an error (error_max_turns): ", [])
    monkeypatch.setattr(CC, "ClaudeCodeProvider", Crash)
    with pytest.raises(CC.CLIError):
        RS.main(["--work-dir", str(work), "--review-file", str(review_file), "--pr", "7", "--fixed-in", "b",
                 "--summary-out", str(tmp_path / "s.md"), "--error-file", str(err), "--author", "claude"])
    assert "Denied commands (1): Bash: mkdir -p /tmp/a" in err.read_text()


def test_denials_note_is_short():
    out = RS.denials_note([{"tool": "Bash", "command": "c"}] * 7)
    assert out.startswith(" Denied commands (7): Bash: c") and out.endswith(" …")
    assert RS.denials_note([]) == "" and RS.denials_note(None) == ""


# ---- GPT Sol's re-check of #10: default deny ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    f"redis-cli -a {FAKE} ping",                          # a password as a flag's plain value
    f"redis-cli --pass {FAKE} ping",
    f"mysql db {FAKE}",                                   # a password as a plain positional word
    f'PASSWORD="correct horse {FAKE}" python x.py',       # quoted multi-word assignment
    f"DB_URL='postgres://u:{FAKE}@db/x' python x.py",
    f"env MYSECRET={FAKE} python x.py",
    f'curl -d "{{\"password\": \"{FAKE}\"}}" https://x.io',
    f"sshpass -p {FAKE} ssh host",
    f'echo "{FAKE}',                                      # unbalanced quote: fail closed, nothing shown
    f"tool --token={FAKE}",
])
def test_unknown_values_are_denied_by_default(cmd):
    out = CC.safe_command(cmd)
    assert FAKE not in out and "horse" not in out and "correct" not in out, out


def test_parse_errors_fail_closed():
    assert CC.safe_command(f'cat "{FAKE}\nmore') == "(command not shown: it could not be parsed safely) (+1 more line)"


# ---- GPT Sol's re-check at 55f950c: role, not appearance ----------------------------------------------------------------

@pytest.mark.parametrize("cmd, secret", [
    (f"redis-cli -a {FAKE}.txt ping", FAKE),                    # path-shaped password
    (f"redis-cli -a /tmp/{FAKE} ping", FAKE),
    ("redis-cli -a build ping", "build"),                       # a password spelled like a known word
    ("mysql -u root -p status db", "status"),
    ("tool --password /tmp/x.py", "/tmp/x.py"),
    ("python -c build", "build"),
    (f"python x.py {FAKE}.txt", FAKE),                          # a script's own arguments
    ("git commit -m build", "build"),
    (f"git push https://u:{FAKE}@x.io/o/r", FAKE),
    ("sshpass -p build.py ssh host", "build.py"),
    ("env SECRET=build python x.py", "build"),
])
def test_a_value_is_hidden_whatever_it_looks_like(cmd, secret):
    out = CC.safe_command(cmd)
    assert secret not in out, (cmd, out)


# ---- GPT Sol's re-check at c89fb64: interpreter options end at code, module or script --------------------------------

@pytest.mark.parametrize("cmd, secret", [
    (f"python -c 'import sys; print(len(sys.argv[1]))' {FAKE}.py", FAKE),   # after -c
    (f"python -m build {FAKE}.py", FAKE),                                   # after an unknown module
    (f"python -m pip install {FAKE}.py", FAKE),                             # after a known non-test module
    (f"python x.py y.py {FAKE}.py", FAKE),                                  # after the script
    (f"python - {FAKE}.py", FAKE),                                          # after a script from stdin
    (f"python3 -c x -m pytest {FAKE}.py", FAKE),                            # -m after -c is the code's argument
    (f"python -I -c x {FAKE}.py", FAKE),
])
def test_arguments_after_code_module_or_script_are_hidden(cmd, secret):
    assert secret not in CC.safe_command(cmd), CC.safe_command(cmd)


# ---- GPT Sol's re-check at 0a7d429: attached options fail closed ------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    f"python -c'import sys; print(len(sys.argv[1]))' {FAKE}.py",   # code attached to -c (CPython accepts it)
    f"python -mbuild {FAKE}.py",                                    # module attached to -m
    f"python -mpytest {FAKE}.py",
    f"python -Wignore x.py {FAKE}",                                 # value attached to -W
    f"python -Xdev {FAKE}.py",
    f"python --unknown {FAKE}.py",                                  # an option the view doesn't know
    f"python -m pytest -kfoo {FAKE}.py",                            # attached option inside pytest's arguments
    f"python -m pytest --weird {FAKE}.py",
    f"pytest -kfoo {FAKE}.py",
    f"cat -Z {FAKE}",
    f"git --work-tree={FAKE} status",
])
def test_unrecognised_or_attached_options_hide_every_argument(cmd):
    out = CC.safe_command(cmd)
    assert FAKE not in out, out




# ---- shape only (Xin Jie's decision after GPT Sol's re-checks of #10) --------------------------------------------------

@pytest.mark.parametrize("cmd, expect", [
    ("python -m pytest tests/t.py -k x", "python -m *** *** -k ***"),
    (f"PASSWORD='a b {FAKE}' python x.py", "PASSWORD=*** python ***"),
    (f"./{FAKE} -x", "*** -x"),                                # a program given as a path is hidden too
    (f"/usr/bin/env {FAKE}=1 python", "*** *** ***"),
    (f"cat {FAKE} | grep -n x > out.txt 2>&1", "cat *** | grep -n *** > *** 2>&1"),
    ("python", "python"),
    ("", ""),
])
def test_only_program_names_flags_and_operators_are_shown(cmd, expect):
    assert CC.safe_command(cmd) == expect


@pytest.mark.parametrize("word", ["hunter2", "hunter2.py", "/tmp/hunter2", "build", "status", "pytest",
                                  "https://x.io/r", "a:b", "x=y"])
def test_no_argument_value_is_ever_shown_whatever_it_looks_like(word):
    for cmd in (f"tool {word}", f"tool -a {word}", f"tool --opt {word}", f"python -c x {word}", f"git {word}"):
        assert CC.safe_command(cmd).split(" ", 1)[1].count("***") >= 1
        assert word not in CC.safe_command(cmd).split(" ", 1)[1].replace("-a", "").replace("--opt", ""), cmd
