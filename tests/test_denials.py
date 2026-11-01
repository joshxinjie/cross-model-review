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
    assert c.denials == [{"tool": "Bash", "command": "mkdir -p /tmp/sim && cat > /tmp/sim/s.py"},
                         {"tool": "Write", "command": "/etc/passwd"}, {"tool": "Bash", "command": ""}]
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
