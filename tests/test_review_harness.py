"""Cross-model review harness (review_harness): offline tests, no API calls."""

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]          # this repository: harness code and workflows
ROOT = REPO / "tests" / "fixture"                    # the project under review (conftest sets it)
sys.path.insert(0, str(REPO))

from review_harness import context as C  # noqa: E402
from review_harness import post as P  # noqa: E402
from review_harness import run as R  # noqa: E402
from review_harness.config import get_reviewer, load_config  # noqa: E402
from review_harness.diff import parse_unified_diff  # noqa: E402
from review_harness.providers.anthropic import AnthropicProvider  # noqa: E402
from review_harness.providers.base import Completion, Provider  # noqa: E402
from review_harness.validate import (derive_verdict, extract_json, schema_errors,  # noqa: E402
                                     semantic_errors)

CFG = load_config(ROOT)
SCHEMA = json.loads((REPO / "review_harness" / "schemas" / "review.json").read_text())


def finding(**kw):
    f = {"id": "F1", "severity": "minor", "area": "code", "title": "t", "file": "README.md", "line_start": 3,
         "claim": "c", "evidence": "e", "proposed_change": "p", "verified_by": "read_code", "confidence": 0.7}
    f.update(kw)
    return f


def review(scope="pr", verdict="approve_with_nits", findings=None):
    return {"schema_version": 1, "scope": scope, "verdict": verdict, "summary": "s",
            "findings": [finding()] if findings is None else findings}


# ---- diff -----------------------------------------------------------------------------------------------------------

def test_diff_lines_and_header_lookalikes():
    d = ("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,4 @@\n a\n-b\n+++ c\n+d\n e\n"
         "diff --git a/new.md b/new.md\nnew file mode 100644\n--- /dev/null\n+++ b/new.md\n@@ -0,0 +1,2 @@\n+one\n+two\n"
         "\\ No newline at end of file\n"
         "diff --git a/gone.py b/gone.py\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n")
    m = parse_unified_diff(d)
    assert m["x.py"] == {"added": {2, 3}, "commentable": {1, 2, 3, 4}}
    assert m["new.md"]["added"] == {1, 2}
    assert "gone.py" not in m and "+++ c" not in str(m.keys())


# ---- validation -----------------------------------------------------------------------------------------------------

def test_valid_review_passes():
    assert schema_errors(review(), SCHEMA) == []
    assert semantic_errors(review(), "pr", ROOT) == []


@pytest.mark.parametrize("mutate, expect", [
    (lambda r: r.pop("summary"), "missing required field 'summary'"),
    (lambda r: r["findings"][0].update(severity="huge"), "not one of"),
    (lambda r: r.update(extra=1), "unexpected field 'extra'"),
    (lambda r: r["findings"][0].update(confidence=1.5), "above 1"),
    (lambda r: r["findings"][0].update(id="X1"), "does not match"),
    (lambda r: r.update(findings=[finding(id=f"F{k}") for k in range(16)]), "more than 15 items"),
    (lambda r: r["findings"][0].update(line_start="3"), "expected integer"),
])
def test_schema_rejects(mutate, expect):
    r = review()
    mutate(r)
    assert any(expect in e for e in schema_errors(r, SCHEMA))


def test_semantic_errors():
    r = review(verdict="healthy", findings=[finding(), finding(file="nope/missing.py#x"),
                                            finding(id="F2", line_start=9, line_end=4)])
    errs = " ".join(semantic_errors(r, "pr", ROOT))
    assert "not a pr-scope verdict" in errs and "unique" in errs
    assert "does not exist" in errs and "line_end before line_start" in errs
    assert semantic_errors(review(findings=[finding(file="METHODOLOGY.md#v1 model")]), "pr", ROOT) == []


@pytest.mark.parametrize("scope, sevs, verdict", [
    ("pr", [], "approve"), ("pr", ["nit", "question"], "approve"), ("pr", ["minor"], "approve_with_nits"),
    ("pr", ["minor", "major"], "changes_needed"), ("project", ["minor"], "healthy"),
    ("project", ["major"], "attention"), ("project", ["critical", "nit"], "at_risk"),
])
def test_derive_verdict(scope, sevs, verdict):
    assert derive_verdict(scope, [{"severity": s} for s in sevs]) == verdict


def test_extract_json():
    assert extract_json('Sure:\n```json\n{"a": {"b": 1}}\n```\nDone')["a"]["b"] == 1
    assert extract_json('{"a": 1}')["a"] == 1
    with pytest.raises(ValueError):
        extract_json("no json here")


# ---- run loop -------------------------------------------------------------------------------------------------------

class FakeProvider(Provider):
    model = "fake"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def complete(self, system, messages, max_output_tokens):
        self.calls.append(copy.deepcopy(messages))
        return Completion(self.replies.pop(0), 100, 10)


PACK = {"scope": "pr", "text": "===== DIFF =====\n", "files": ["DIFF"], "dropped": [], "tokens": 5,
        "diff": "", "changed": [], "dependents": []}
REVIEWER = {"name": "fable", "provider": "anthropic", "model": "claude-fable-5-1"}


def test_run_retries_then_corrects_verdict_and_sorts():
    good = review(verdict="approve", findings=[finding(id="F1", severity="nit"), finding(id="F2", severity="major")])
    fake = FakeProvider(["not json", json.dumps(good)])
    env = R.run_review(ROOT, CFG, REVIEWER, fake, PACK)
    assert env["meta"]["attempts"] == 2 and "invalid" not in env["meta"]
    assert env["review"]["verdict"] == "changes_needed" and env["meta"]["verdict_adjusted_from"] == "approve"
    assert [f["id"] for f in env["review"]["findings"]] == ["F2", "F1"]
    assert env["meta"]["input_tokens"] == 200
    retry = fake.calls[1]
    assert retry[1]["role"] == "assistant" and "did not pass validation" in retry[2]["content"]


def test_run_gives_up_after_one_retry():
    env = R.run_review(ROOT, CFG, REVIEWER, FakeProvider(["{}", "{}"]), PACK)
    assert env["meta"]["attempts"] == 2 and env["meta"]["invalid"]


def test_prompt_is_blind_and_carries_instructions():
    from review_harness.prompt import build_prompt
    system, user = build_prompt(ROOT, CFG, PACK)
    assert "Cross-model review procedure" in system and '"schema_version"' in system
    assert "claude-opus" not in system + user


def test_output_path_never_overwrites(tmp_path):
    (tmp_path / "reviews").mkdir()
    first = R.output_path(tmp_path, "2026-10-14", "pr25", "fable")
    first.write_text("{}")
    assert R.output_path(tmp_path, "2026-10-14", "pr25", "fable").name == "2026-10-14-pr25-fable-2.json"


# ---- context --------------------------------------------------------------------------------------------------------

def test_sanitize_strips_attribution():
    text = "Fix bug\n\nCo-Authored-By: Claude Opus <x>\nClaude-Session: https://claude.ai/code/session_1\nkeep\n"
    assert C.sanitize(text) == "Fix bug\n\nkeep\n"


def test_fit_to_budget_drops_low_priority_first_and_never_drops_priority_zero():
    items = [C.Item("diff", "x" * 4000, 0), C.Item("dep", "y" * 8000, 2), C.Item("changed", "z" * 4000, 1)]
    kept, dropped = C.fit_to_budget(items, 2100)
    assert dropped == ["dep"] and [i.label for i in kept] == ["diff", "changed"]
    kept, dropped = C.fit_to_budget([C.Item("diff", "x" * 40000, 0)], 1000)
    assert kept[0].label == "diff" and "truncated" in dropped[0] and kept[0].tokens < 10000


def test_build_pr_pack_finds_changes_and_dependents(tmp_path):
    def sh(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    sh("init", "-q", "-b", "main")
    sh("config", "user.email", "t@t")
    sh("config", "user.name", "t")
    (tmp_path / "models").mkdir()
    (tmp_path / "REVIEW.md").write_text("instructions")
    (tmp_path / "METHODOLOGY.md").write_text("method")
    (tmp_path / "models" / "signal.py").write_text("def f():\n    return 1\n")
    (tmp_path / "models" / "user.py").write_text("from signal import f\n")
    (tmp_path / "models" / "other.py").write_text("x = 1\n")
    sh("add", "-A")
    sh("commit", "-qm", "base")
    sh("checkout", "-qb", "feature")
    (tmp_path / "models" / "signal.py").write_text("def f():\n    return 2\n")
    sh("commit", "-qam", "change")
    pack = C.build_pr_pack(tmp_path, CFG, "main", "feature", "Title",
                           "Body\nCo-Authored-By: Claude <noreply@anthropic.com>")
    assert pack["changed"] == ["models/signal.py"] and pack["dependents"] == ["models/user.py"]
    assert "REVIEW.md" not in pack["files"] and "METHODOLOGY.md" in pack["files"]
    assert "+    return 2" in pack["text"] and "Co-Authored-By" not in pack["text"]


def test_project_pack_respects_excludes():
    pack = C.build_project_pack(ROOT, CFG, ["evaluation/"])
    assert pack["files"][0] in CFG["context"]["project"]["always"]
    assert any(f.startswith("evaluation/") for f in pack["files"])
    assert not any(f.endswith(".csv") for f in pack["files"]) and "REVIEW.md" not in pack["files"]


# ---- posting --------------------------------------------------------------------------------------------------------

def envelope(findings):
    return {"meta": {"reviewer": "fable", "model": "claude-fable-5-1", "input_tokens": 1000, "output_tokens": 100,
                     "context_dropped": []},
            "review": review(verdict=derive_verdict("pr", findings), findings=findings)}


def test_plan_comments_and_summary():
    diff_map = {"models/a.py": {"added": {10, 11}, "commentable": {8, 9, 10, 11, 12}}}
    fs = [finding(id="F1", severity="major", file="models/a.py", line_start=10, line_end=12),
          finding(id="F2", file="models/a.py", line_start=40), finding(id="F3", file="README.md")]
    inline, rest = P.plan_comments(fs, diff_map)
    assert len(inline) == 1 and inline[0]["line"] == 12 and inline[0]["start_line"] == 10
    assert [f["id"] for f in rest] == ["F2", "F3"]
    text = P.render_summary(envelope(fs), rest, closing="_Not advice._")       # the project's footer, if any
    assert "changes_needed" in text and text.rstrip().endswith("_Not advice._") and "F2" in text
    assert "_Not advice._" not in P.render_summary(envelope(fs), rest)
    assert text.index("F1") < text.index("<details>")      # top findings come before the details


def test_post_falls_back_when_inline_positions_rejected():
    class Resp:
        def __init__(self, code):
            self.status_code = code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

        def json(self):
            return {"html_url": "u"}

    class Session:
        def __init__(self):
            self.payloads = []

        def post(self, url, json, headers, timeout):
            self.payloads.append(json)
            return Resp(422 if len(self.payloads) == 1 else 200)

    s = Session()
    out = P.post_pr_review("o/r", 1, "abc", "body", [{"path": "a", "line": 1, "body": "b"}], "tok", s)
    assert out["html_url"] == "u" and s.payloads[0]["event"] == "COMMENT"
    assert "comments" not in s.payloads[1] and "GitHub rejected" in s.payloads[1]["body"]


# ---- config and provider --------------------------------------------------------------------------------------------

def test_get_reviewer_guards():
    assert get_reviewer(CFG)["model"] == "claude-fable-5-1"
    with pytest.raises(ValueError, match="disabled"):
        get_reviewer(CFG, "gemini")
    bad = copy.deepcopy(CFG)
    bad["reviewers"]["fable"]["model"] = bad["authors"]["claude"]["model"]
    with pytest.raises(ValueError, match="built this work"):
        get_reviewer(bad)


def test_anthropic_adapter_parses_and_retries(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr("review_harness.providers.anthropic.time.sleep", lambda s: None)

    class Resp:
        def __init__(self, code, data=None):
            self.status_code, self._data, self.headers, self.text = code, data, {}, ""

        def json(self):
            return self._data

    class Session:
        def __init__(self):
            self.n, self.payload = 0, None

        def post(self, url, json, headers, timeout):
            self.n += 1
            self.payload = json
            if self.n == 1:
                return Resp(529)
            return Resp(200, {"content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn",
                              "usage": {"input_tokens": 7, "output_tokens": 3}})

    s = Session()
    c = AnthropicProvider({"model": "claude-fable-5-1", "secret": "ANTHROPIC_API_KEY"}, s) \
        .complete("sys", [{"role": "user", "content": "u"}], 100)
    assert (c.text, c.input_tokens, c.output_tokens, s.n) == ("{}", 7, 3, 2)
    assert s.payload["model"] == "claude-fable-5-1" and s.payload["system"] == "sys"


# ---- workflow gate --------------------------------------------------------------------------------------------------

from review_harness import gate as G  # noqa: E402

TODAY = "2026-11-06"


def pr_json(number=7, ref="feature/x", state="open", fork=False):
    base_repo = {"full_name": "owner/project"}
    head_repo = {"full_name": "someone/fork"} if fork else base_repo
    return {"number": number, "state": state, "title": "T\nitle", "body": "B",
            "head": {"ref": ref, "sha": "abc123", "repo": head_repo}, "base": {"ref": "main", "repo": base_repo}}


def comment_event(body, assoc="OWNER", number=7):
    return {"issue": {"number": number, "pull_request": {}}, "comment": {"body": body, "author_association": assoc}}


@pytest.mark.parametrize("body, expect", [
    ("/review", (True, None)), ("/review fable", (True, "fable")), ("/review  GPT \nplease", (True, "gpt")),
    ("/reviewer", (False, None)), ("please /review", (False, None)), ("/review a b", (False, None)), ("", (False, None)),
])
def test_parse_command(body, expect):
    assert G.parse_command(body) == expect


def test_gate_comment_runs_and_rejects():
    get = lambda path: pr_json()  # noqa: E731
    out = G.resolve("issue_comment", comment_event("/review"), {}, CFG, get, [], TODAY)
    assert out["run"] == "true" and out["scope"] == "pr" and out["reviewer"] == "gpt" and out["author"] == "claude"
    assert out["head_sha"] == "abc123" and out["base"] == "main"
    assert G.resolve("issue_comment", comment_event("/review", "NONE"), {}, CFG, get, [], TODAY)["run"] == "false"
    msg = G.resolve("issue_comment", comment_event("/review gemini"), {}, CFG, get, [], TODAY)["message"]
    assert "disabled" in msg
    assert G.resolve("issue_comment", comment_event("thanks!"), {}, CFG, get, [], TODAY) == G.skip()


@pytest.mark.parametrize("pr, why", [
    (pr_json(state="closed"), "not open"), (pr_json(fork=True), "forks"), (pr_json(ref="reviewer/project-x"), ""),
])
def test_gate_skips(pr, why):
    out = G.resolve("issue_comment", comment_event("/review"), {}, CFG, lambda p: pr, [], TODAY)
    assert out["run"] == "false" and why in out["message"]


def test_gate_daily_limit_counts_only_this_pr_today():
    limit = CFG["limits"]["max_runs_per_pr_per_day"]
    files = [f"reviews/{TODAY}-pr7-fable{'' if k == 0 else f'-{k + 1}'}.json" for k in range(limit)]
    files += [f"reviews/{TODAY}-pr70-fable.json", "reviews/2026-11-05-pr7-fable.json"]
    assert G.runs_today(files, TODAY, 7) == limit
    out = G.resolve("issue_comment", comment_event("/review"), {}, CFG, lambda p: pr_json(), files, TODAY)
    assert out["run"] == "false" and "already had" in out["message"]


def test_gate_label_dispatch_and_schedule():
    label = {"label": {"name": "review"}, "pull_request": {"number": 7}}
    assert G.resolve("pull_request", label, {}, CFG, lambda p: pr_json(), [], TODAY)["run"] == "true"
    other = {"label": {"name": "bug"}, "pull_request": {"number": 7}}
    assert G.resolve("pull_request", other, {}, CFG, lambda p: pr_json(), [], TODAY)["run"] == "false"
    proj = G.resolve("workflow_dispatch", {}, {"scope": "project", "areas": "evaluation"}, CFG, None, [], TODAY)
    assert proj["scope"] == "project" and proj["areas"] == "evaluation"
    assert "PR number" in G.resolve("workflow_dispatch", {}, {"scope": "pr", "pr": ""}, CFG, None, [], TODAY)["message"]
    pulls = [pr_json(3, "feature/y"), pr_json(9, "review/2026-11")]
    monthly_cron = next(s["cron"] for s in CFG["schedules"] if s["kind"] == "pr")       # from the project's config
    project_cron = next(s["cron"] for s in CFG["schedules"] if s["kind"] == "project")
    monthly = G.resolve("schedule", {"schedule": monthly_cron}, {}, CFG, lambda p: pulls, [], TODAY)
    assert monthly["run"] == "true" and monthly["pr"] == "9"
    none = G.resolve("schedule", {"schedule": monthly_cron}, {}, CFG, lambda p: pulls[:1], [], TODAY)
    assert none["run"] == "false" and "review/2026-11" in none["message"]
    assert G.resolve("schedule", {"schedule": project_cron}, {}, CFG, None, [], TODAY)["scope"] == "project"
    unknown = G.resolve("schedule", {"schedule": "0 0 1 1 *"}, {}, CFG, None, [], TODAY)
    assert unknown["run"] == "false" and "No schedule" in unknown["message"]


def test_gate_outputs_are_single_line(tmp_path):
    out, body = tmp_path / "out", tmp_path / "body.md"
    G.write_outputs(G.pr_target(CFG, pr_json(), None, [], TODAY), str(out), str(body))
    lines = out.read_text().splitlines()
    assert "title=T itle" in lines and body.read_text() == "B" and not any(ln.startswith("body=") for ln in lines)


def test_workflow_matches_gate_and_never_approves():
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "review.yml").read_text())
    on = wf.get("on", wf.get(True))            # PyYAML reads the key "on" as True
    assert set(on) == {"workflow_call"}        # reusable: each project's own workflow has the triggers
    text = (REPO / ".github" / "workflows" / "review.yml").read_text()
    assert "review_harness.gate" in text and "APPROVE" not in text and "--force" not in text
    # Harness, trusted project main and the PR each in their own folder; the PR checkout is left as pushed.
    assert 'echo "PYTHONPATH=$RUNNER_TEMP/harness" >> "$GITHUB_ENV"' in text
    assert 'git worktree add -q --detach "$RUNNER_TEMP/project" HEAD' in text
    assert 'REVIEW_PROJECT_ROOT=$RUNNER_TEMP/project' in text and "git checkout -q origin/main --" not in text
    assert text.count('--repo-dir "$GITHUB_WORKSPACE"') == 3 and "scripts" not in text
    caller = (REPO / "templates" / "workflows" / "review.yml").read_text()
    assert CFG["triggers"]["pr_label"] in caller and CFG["triggers"]["pr_comment_command"] in caller


def test_failures_write_a_short_redacted_reason(tmp_path, monkeypatch):
    err = tmp_path / "err.txt"
    R.report_error(str(err), "RuntimeError: Anthropic API 401 for key sk-ant-abcdefghijklmnop " + "x" * 2000)
    text = err.read_text()
    assert "401" in text and "sk-ant" not in text and "[redacted]" in text and len(text) <= 801
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    err2 = tmp_path / "err2.txt"
    with pytest.raises(RuntimeError):
        R.main(["--scope", "project", "--areas", "README.md", "--error-file", str(err2)])
    assert "CLAUDE_CODE_OAUTH_TOKEN is not set" in err2.read_text()


# ---- Claude Code (subscription) reviewer ----------------------------------------------------------------------------

from review_harness.providers import claude_code as CCP  # noqa: E402


def test_claude_code_command_is_read_only_and_schema_bound():
    cmd = CCP.build_command("claude-fable-5-1", "/tmp/sys.md", SCHEMA, 40)
    joined = " ".join(cmd)
    assert cmd[:2] == ["claude", "-p"] and "--json-schema" in cmd and "--no-session-persistence" in cmd
    schema_arg = json.loads(cmd[cmd.index("--json-schema") + 1])
    assert "$schema" not in schema_arg and schema_arg["required"] == SCHEMA["required"]
    assert cmd[cmd.index("--permission-prompts") + 1] == "none"
    allowed = cmd[cmd.index("--allowedTools") + 1: cmd.index("--disallowedTools")]
    assert "Edit" not in allowed and "Bash" not in allowed            # bash only through the listed patterns
    assert all(a in CCP.READ_TOOLS or a.startswith("Bash(") or a == "WebSearch" for a in allowed)
    denied = cmd[cmd.index("--disallowedTools") + 1: cmd.index("--permission-prompts")]
    assert "WebSearch" in allowed and "WebFetch" in denied and "WebSearch" not in denied   # search, never fetch
    assert "Edit Write" in joined and "--dangerously-skip-permissions" not in joined


def test_claude_code_env_drops_github_token_and_api_keys():
    environ = {"PATH": "/bin", "HOME": "/h", "CLAUDE_CODE_OAUTH_TOKEN": "t", "GITHUB_TOKEN": "g",
               "GH_TOKEN": "g", "ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "o"}
    assert CCP.agent_env("CLAUDE_CODE_OAUTH_TOKEN", environ) == {"PATH": "/bin", "HOME": "/h",
                                                                 "CLAUDE_CODE_OAUTH_TOKEN": "t"}


def test_claude_code_provider_runs_cli_and_parses(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    seen = {}

    class Proc:
        returncode = 0
        stderr = ""
        stdout = json.dumps({"is_error": False, "subtype": "success", "result": "ignored",
                             "structured_output": review(), "usage": {"input_tokens": 5, "cache_read_input_tokens": 95,
                                                                      "output_tokens": 7}})

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        assert open(cmd[cmd.index("--append-system-prompt-file") + 1]).read() == "SYS"
        return Proc()

    p = CCP.ClaudeCodeProvider({"model": "claude-fable-5-1", "secret": "CLAUDE_CODE_OAUTH_TOKEN"}, run=fake_run)
    msgs = [{"role": "user", "content": "U"}, {"role": "assistant", "content": "A"}, {"role": "user", "content": "F"}]
    c = p.complete("SYS", msgs, 100)
    assert json.loads(c.text)["verdict"] == "approve_with_nits" and (c.input_tokens, c.output_tokens) == (100, 7)
    assert seen["input"].startswith("U") and "Your previous reply" in seen["input"] and "Feedback" in seen["input"]
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "tok" and "GITHUB_TOKEN" not in seen["env"]
    assert seen["cwd"] == ROOT and 0 < 60 * CFG["limits"]["agent_timeout_minutes"] - seen["timeout"] < 5


def test_claude_code_token_line_breaks_are_removed():
    env = CCP.agent_env("CLAUDE_CODE_OAUTH_TOKEN", {"PATH": "/bin", "CLAUDE_CODE_OAUTH_TOKEN": " sk-ant-oat01-abc\ndef \n"})
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-abcdef"


def test_claude_code_errors_are_reported(monkeypatch):
    with pytest.raises(RuntimeError, match="error_max_turns"):
        CCP.parse_output(json.dumps({"is_error": True, "subtype": "error_max_turns", "result": ""}))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="CLAUDE_CODE_OAUTH_TOKEN is not set"):
        CCP.ClaudeCodeProvider({"model": "m", "secret": "CLAUDE_CODE_OAUTH_TOKEN"}, run=lambda *a, **k: None)


def test_default_reviewer_uses_the_subscription_and_gate_reports_provider():
    r = get_reviewer(CFG)                                  # project reviews: Fable on the Claude subscription
    assert r["provider"] == "claude-code" and r["secret"] == "CLAUDE_CODE_OAUTH_TOKEN"
    out = G.pr_target(CFG, pr_json(), None, [], TODAY)     # a Claude-built PR: GPT through Codex, queued
    assert out["provider"] == "codex" and out["codex"] == "true"
    out = G.pr_target(CFG, pr_json(ref="codex/add-x"), None, [], TODAY)   # a Codex-built PR: Opus
    assert out["provider"] == "claude-code" and out["reviewer"] == "opus" and out["author"] == "codex"


# ---- /respond (author response, M5) ---------------------------------------------------------------------------------

from review_harness import respond as RS  # noqa: E402

LOG = (ROOT / "reviews" / "decisions.md").read_text()
RESP_SCHEMA = json.loads((REPO / "review_harness" / "schemas" / "respond.json").read_text())


def env_with(findings):
    return {"meta": {"reviewer": "fable", "model": "claude-fable-5-1"},
            "review": review(verdict=derive_verdict("pr", findings), findings=findings)}


def answer(fid, decision="accept", reason="right", changes="x.py"):
    return {"finding_id": fid, "decision": decision, "reason": reason, "changes": changes}


def resp_json(answers, passed=True):
    return {"schema_version": 1, "summary": "2 accepted", "responses": answers,
            "tests": {"ran": True, "passed": passed, "detail": "300 passed"}}


def test_decision_log_rows_follow_the_log_convention():
    env = env_with([finding(id="F1", severity="major", title="first"), finding(id="F2", severity="nit")])
    name = "2026-10-20-pr40-fable.json"
    assert RS.row_prefix(LOG, name) == "PR40"                     # no earlier review of #40 in the log
    rows = RS.decision_rows([answer("F2", "reject", "wrong | see line 3\nok", "none"), answer("F1")], env,
                            name, "PR40", "2026-10-20", "respond/pr40-2026-10-20")
    assert rows[0].startswith(f"| PR40-F2 | 2026-10-20 | [{name}]({name}) (copy of `reviewer/archive`) | F2: t | "
                              "fable | nit | reject |")
    assert "wrong / see line 3 ok" in rows[0] and rows[0].endswith("| — |")
    assert rows[1].startswith("| PR40-F1 |") and rows[1].endswith("| respond/pr40-2026-10-20 |")
    log = RS.insert_rows(LOG, rows)
    assert log.index("PR40-F2") > log.index("|---|") and RS.decided(log, name) == {"F1", "F2"}
    assert RS.row_prefix(log, name) == "PR40"                     # reused for a partial second answer
    assert RS.row_prefix(log, "2026-10-21-pr40-fable.json") == "PR40-2"
    assert RS.row_prefix(LOG, "2026-10-21-project-fable.json") == "PROJ-2026-10-21"
    assert RS.decided(log, "2026-10-20-pr40-fable-2.json") == set()   # no prefix collision between files
    assert schema_errors(resp_json([answer("F1")]), RESP_SCHEMA) == []


def test_existing_log_rows_are_recognised():
    """The log on main uses linked review cells and 'F1: title' findings; /respond must see them as decided."""
    assert RS.decided(LOG, "2026-10-13-pr31-fable.json") >= {"F1", "F11"}
    assert RS.decided(LOG, "2026-10-13-pr31-fable-2.json") >= {"F1", "F5"}
    assert "F6" not in RS.decided(LOG, "2026-10-13-pr31-fable-2.json")
    assert RS.row_prefix(LOG, "2026-10-14-pr31-fable.json") == "PR31-4"
    assert RS.row_prefix(LOG, "2026-10-20-pr31-fable.json") == "PR31-5"
    pattern = SCHEMA["$defs"]["finding"]["properties"]["related_decision"]["pattern"]
    ids = [c[0] for c in RS.table_rows(LOG)]
    assert ids and all(re.match(pattern, i) for i in ids)


def test_response_must_answer_each_pending_finding_once():
    errs = RS.response_errors(resp_json([answer("F1"), answer("F1"), answer("F9")]), RESP_SCHEMA, ["F1", "F2"])
    joined = " ".join(errs)
    assert "no answer for: F2" in joined and "not asked about: F9" in joined and "more than one answer for: F1" in joined
    assert RS.response_errors(resp_json([answer("F1", "maybe")]), RESP_SCHEMA, ["F1"])


def scratch_repo(tmp_path):
    def sh(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    sh("init", "-q", "-b", "main")
    sh("config", "user.email", "t@t")
    sh("config", "user.name", "t")
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "decisions.md").write_text(LOG)
    (tmp_path / "REVIEW.md").write_text("rules\n")
    (tmp_path / "x.py").write_text("x = 1\n")
    sh("add", "-A")
    sh("commit", "-qm", "base")
    return tmp_path


class EditingAuthor(Provider):
    """Fake author: edits x.py, tries to edit REVIEW.md and add a review file, then answers."""
    model = "fake-author"

    def __init__(self, work, replies):
        self.work, self.replies, self.calls = work, list(replies), 0

    def complete(self, system, messages, max_output_tokens):
        self.calls += 1
        (self.work / "x.py").write_text("x = 2\n")
        (self.work / "REVIEW.md").write_text("weakened rules\n")
        (self.work / "reviews" / "fake.json").write_text("{}")
        return Completion(self.replies.pop(0), 1, 1)


def test_respond_applies_logs_and_undoes_protected_edits(tmp_path):
    work = scratch_repo(tmp_path)
    env = env_with([finding(id="F1", severity="major"), finding(id="F2", severity="minor")])
    good = json.dumps(resp_json([answer("F1"), answer("F2", "defer", "later", "research/backlog.md item")]))
    author = EditingAuthor(work, ["{not json", good])
    out = RS.respond(ROOT, CFG, author, work, env, "2026-10-14-pr7-fable.json", 7, "main", "respond/pr7-x",
                     date="2026-10-14")
    assert out["status"] == "done" and author.calls == 2
    assert (work / "x.py").read_text() == "x = 2\n"                      # the fix stays
    assert (work / "REVIEW.md").read_text() == "rules\n"                  # protected edit undone
    assert not (work / "reviews" / "fake.json").exists()
    assert set(out["reverted"]) == {"REVIEW.md", "reviews/fake.json"}
    log = (work / "reviews" / "decisions.md").read_text()
    assert ("| PR7-F1 | 2026-10-14 | [2026-10-14-pr7-fable.json](2026-10-14-pr7-fable.json) (copy of `reviewer/archive`) "
            "| F1: t | fable | major | accept |") in log
    assert "| F2: t | fable | minor | defer | later | research/backlog.md item |" in log
    assert json.loads((work / "reviews" / "2026-10-14-pr7-fable.json").read_text()) == env
    s = out["summary"]
    assert "✅ 1 accept" in s and "⏳ 1 defer" in s and "tests pass" in s and "undone: " in s
    assert "not financial advice" in s and "Merging this pull request accepts" in s
    again = RS.respond(ROOT, CFG, EditingAuthor(work, []), work, env, "2026-10-14-pr7-fable.json", 7, "main", "b")
    assert again == {"status": "nothing", "already": ["F1", "F2"]}


def test_respond_invalid_answer_leaves_log_unchanged(tmp_path):
    work = scratch_repo(tmp_path)
    env = env_with([finding(id="F1")])
    out = RS.respond(ROOT, CFG, EditingAuthor(work, ["{}", "{}"]), work, env, "r.json", 7, "main", "b")
    assert out["status"] == "invalid" and (work / "reviews" / "decisions.md").read_text() == LOG
    with pytest.raises(ValueError, match="failed validation"):
        RS.respond(ROOT, CFG, EditingAuthor(work, []), work, {"meta": {"invalid": ["x"]}, "review": None},
                   "r.json", 7, "main", "b")


def test_respond_prompt_lists_only_pending_findings():
    env = env_with([finding(id="F1"), finding(id="F2", title="second")])
    system, user = RS.build_prompt(ROOT, CFG, env, ["F2"], 7, "main")
    assert "Author response procedure" in system and "exactly these finding IDs: F2." in system
    assert '"F2"' in user and '"F1"' not in user and "git diff origin/main...HEAD" in user


def test_respond_mode_can_edit_but_not_the_review_machinery_or_git_history():
    cmd = CCP.build_command("claude-opus-5-5", "/tmp/s.md", RESP_SCHEMA, 100, mode="respond")
    allowed = cmd[cmd.index("--allowedTools") + 1: cmd.index("--disallowedTools")]
    denied = cmd[cmd.index("--disallowedTools") + 1: cmd.index("--permission-prompts")]
    assert {"Edit", "Write", "Bash(python *)"} <= set(allowed)
    assert {"Bash(git push *)", "Bash(git commit *)", "Edit(./REVIEW.md)", "Write(./.github/**)",
            "Edit(./review/**)", "Edit(./reviews/**)", "WebFetch", "WebSearch"} <= set(denied)
    assert "WebSearch" not in allowed                                   # the author gets no web tools
    with pytest.raises(ValueError):
        CCP.build_command("m", "s", RESP_SCHEMA, 1, mode="anything")


def github(pr=None, open_pulls=()):
    """Stub for gate's get_json: one PR, plus the open-PR list."""
    pr = pr or pr_json()
    return lambda path: list(open_pulls) if path.startswith("pulls?") else pr


def test_gate_respond():
    assert G.parse_respond("/respond") == (True, None)
    assert G.parse_respond("/respond 2026-10-13-pr31-fable.json\nthanks") == (True, "2026-10-13-pr31-fable.json")
    assert G.parse_respond("/respond now") == (False, None) and G.parse_respond("/review") == (False, None)
    newest_first = ["reviews/2026-10-14-pr7-fable-response-020000.json", "reviews/2026-10-14-pr7-fable-response.json",
                    "reviews/2026-10-14-pr7-fable.json", "reviews/2026-10-13-pr7-fable.json",
                    "reviews/2026-10-14-pr70-fable.json"]
    assert G.latest_review(newest_first, 7) == "2026-10-14-pr7-fable.json" and G.latest_review(newest_first, 8) is None
    good = env_with([finding()])
    good["meta"]["commit"] = "abc123"
    read = {"2026-10-14-pr7-fable.json": good, "empty.json": env_with([]),
            "bad.json": {"meta": {"invalid": ["x"]}, "review": None}}.get
    ev = comment_event("/respond")
    out = G.resolve_respond("issue_comment", ev, {}, CFG, github(), newest_first, read)
    assert out["run"] == "true" and out["review"] == "2026-10-14-pr7-fable.json" and out["head_ref"] == "feature/x"
    assert G.resolve_respond("issue_comment", comment_event("/respond", "NONE"), {}, CFG, github(),
                             newest_first, read)["run"] == "false"
    assert "comment /review first" in G.resolve_respond("issue_comment", ev, {}, CFG, github(), [], read)["message"]
    for name, why in (("bad.json", "failed validation"), ("empty.json", "no findings"), ("gone.json", "not found")):
        out = G.resolve_respond("issue_comment", comment_event(f"/respond {name}"), {}, CFG, github(),
                                newest_first, read)
        assert out["run"] == "false" and why in out["message"]
    assert G.resolve_respond("workflow_dispatch", {}, {"pr": "7", "review": ""}, CFG, github(),
                             newest_first, read)["run"] == "true"


def test_respond_waits_for_the_pending_fix_pr_and_for_a_fresh_review():
    newest_first = ["reviews/2026-10-14-pr7-fable.json"]
    env = env_with([finding()])
    env["meta"]["commit"] = "abc123"
    read = {"2026-10-14-pr7-fable.json": env}.get
    pending = [pr_json(38, "respond/pr7-2026-10-14"), pr_json(39, "respond/pr70-2026-10-14")]
    out = G.resolve_respond("issue_comment", comment_event("/respond"), {}, CFG, github(open_pulls=pending),
                            newest_first, read)
    assert out["run"] == "false" and "#38" in out["message"] and "#39" not in out["message"]
    moved = pr_json()
    moved["head"]["sha"] = "def456"
    out = G.resolve_respond("issue_comment", comment_event("/respond"), {}, CFG, github(moved), newest_first, read)
    assert out["run"] == "false" and "new commits since" in out["message"] and "abc123" in out["message"]


def test_review_skips_a_commit_already_reviewed_unless_forced():
    assert G.parse_command("/review force") == (True, None) and G.wants_force("/review force")
    assert G.parse_command("/review fable force") == (True, "fable") and G.wants_force("/review fable force")
    assert not G.wants_force("/review fable") and G.parse_command("/review force now") == (False, None)
    last = lambda n: ("2026-11-06-pr7-fable.json", "abc123")  # noqa: E731
    out = G.resolve("issue_comment", comment_event("/review"), {}, CFG, github(), [], TODAY, last)
    assert out["run"] == "false" and "already reviewed" in out["message"] and "/review force" in out["message"]
    assert G.resolve("issue_comment", comment_event("/review force"), {}, CFG, github(), [], TODAY, last)["run"] == "true"
    moved = pr_json()
    moved["head"]["sha"] = "def456"
    assert G.resolve("issue_comment", comment_event("/review"), {}, CFG, github(moved), [], TODAY, last)["run"] == "true"
    label = {"label": {"name": "review"}, "pull_request": {"number": 7}}
    assert G.resolve("pull_request", label, {}, CFG, github(), [], TODAY, last)["run"] == "false"
    manual = G.resolve("workflow_dispatch", {}, {"scope": "pr", "pr": "7"}, CFG, github(), [], TODAY, last)
    assert manual["run"] == "true"                                  # a manual run is deliberate


def test_review_records_never_overwrite_the_archive(tmp_path):
    (tmp_path / "reviews").mkdir()
    taken = {"2026-10-14-pr37-fable.json", "2026-10-14-pr37-fable-2.json", "2026-10-14-pr37-fable-response.json"}
    assert R.output_path(tmp_path, "2026-10-14", "pr37", "fable", taken).name == "2026-10-14-pr37-fable-3.json"
    files = [f"reviews/{n}" for n in taken] + ["reviews/2026-10-14-pr37-fable-response-020000.json"]
    assert G.runs_today(files, "2026-10-14", 37) == 2               # responses are not reviews


def test_respond_workflow_runs_harness_from_main_and_targets_the_pr_branch():
    text = (REPO / ".github" / "workflows" / "respond.yml").read_text()
    assert "review_harness.gate --respond" in text and 'echo "PYTHONPATH=$RUNNER_TEMP/harness"' in text
    assert "REVIEW_PROJECT_ROOT: ${{ github.workspace }}" in text and "scripts" not in text
    assert '-f base="$HEAD_REF"' in text and "-f base=main" not in text
    assert "APPROVE" not in text and "--force" not in text and "git worktree add -q -b" in text
    assert text.count("secrets.CLAUDE_CODE_OAUTH_TOKEN") == 1
    assert CFG["triggers"]["respond_command"] in (REPO / "templates" / "workflows" / "respond.yml").read_text()


# ---- live progress (stream-json + progress comment) -----------------------------------------------------------------

from review_harness import progress as PG  # noqa: E402


def test_describe_tool_calls(tmp_path):
    assert CCP.describe("Read", {"file_path": str(tmp_path / "plans" / "x.md")}, tmp_path) == "Read `plans/x.md`"
    assert CCP.describe("Bash", {"command": "python  -m pytest\n -q"}, tmp_path) == "Run `python -m pytest -q`"
    assert CCP.describe("Grep", {"pattern": "H23p"}, tmp_path) == "Search for `H23p`"
    assert CCP.describe("StructuredOutput", {}, tmp_path) == "Write the final answer"


def test_stream_reports_steps_and_returns_the_result(tmp_path):
    events = [{"type": "system", "subtype": "init"},
              {"type": "assistant", "message": {"content": [
                  {"type": "text", "text": "hi"},
                  {"type": "tool_use", "name": "Read", "input": {"file_path": str(tmp_path / "README.md")}}]}},
              {"type": "assistant", "message": {"content": [
                  {"type": "tool_use", "name": "Bash", "input": {"command": "python -m pytest -q"}}]}},
              {"type": "result", "is_error": False, "subtype": "success", "structured_output": {"ok": 1},
               "usage": {"input_tokens": 3, "output_tokens": 2}}]
    fake = tmp_path / "fake_cli.py"
    fake.write_text("import sys, json\nsys.stdin.read()\n"
                    + "".join(f"print(json.dumps({e!r}))\n" for e in events))
    steps = []
    out = CCP.stream([sys.executable, str(fake)], "prompt", tmp_path, {"PATH": "/usr/bin:/bin"}, 30, steps.append)
    assert steps == ["Read `README.md`", "Run `python -m pytest -q`"] and out["structured_output"] == {"ok": 1}
    assert CCP.parse_output(json.dumps(out)).text == '{"ok": 1}'
    bad = tmp_path / "bad_cli.py"
    bad.write_text("import sys\nsys.stdin.read()\nprint('not json')\nsys.exit(1)\n")
    with pytest.raises(RuntimeError, match="without a result"):
        CCP.stream([sys.executable, str(bad)], "p", tmp_path, {"PATH": "/usr/bin:/bin"}, 30)


def test_progress_comment_throttles_and_folds_on_finish():
    calls = []

    class Resp:
        status_code = 201

        def json(self):
            return {"id": 99}

    class Session:
        def request(self, method, url, json, timeout, headers):
            calls.append((method, url, json["body"]))
            return Resp()

    now = [0.0]
    env = {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r", "PROGRESS_PR": "37", "RUN_URL": "https://run"}
    p = PG.Progress("Author response", env, Session(), clock=lambda: now[0])
    p.start()
    assert calls[0][0] == "POST" and calls[0][1].endswith("/issues/37/comments") and "⏳" in calls[0][2]
    for k in range(20):
        now[0] += 1
        p.step(f"Read `f{k}.md`")
    assert len(calls) == 2 and calls[1][0] == "PATCH" and calls[1][1].endswith("/issues/comments/99")
    assert "_… " in calls[1][2] and "Read `f14.md`" in calls[1][2]          # only the last steps are shown
    p.finish(True, "decisions ready")
    last = calls[-1][2]
    assert last.startswith("✅ **Author response** — decisions ready") and "<details>" in last and "20. Read" in last
    assert PG.Progress("x", {}).enabled is False                          # no env: does nothing


def test_failing_progress_never_breaks_the_run():
    class Boom:
        def request(self, *a, **k):
            raise ConnectionError("down")

    p = PG.Progress("x", {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r", "PROGRESS_PR": "1"}, Boom())
    p.start()
    p.step("Read `a`")
    p.finish(False, "err")
    assert p.steps == ["Read `a`"]


# ---- /respond on a project-review PR --------------------------------------------------------------------------------

def test_respond_on_a_project_review_pr():
    name = "2026-10-14-project-fable.json"
    assert G.project_review_name("reviewer/2026-10-14-project-fable") == name
    assert G.project_review_name("reviewer/2026-10-14-project-fable-2") == "2026-10-14-project-fable-2.json"
    assert G.project_review_name("feature/project-x") is None and G.project_review_name("reviewer/other") is None
    env = env_with([finding()])
    env["review"]["scope"], env["review"]["verdict"] = "project", "attention"
    env["meta"]["commit"] = "main000"                     # main as reviewed; the PR head (main + record) differs
    pr = pr_json(49, "reviewer/2026-10-14-project-fable")
    out = G.resolve_respond("issue_comment", comment_event("/respond", number=49), {}, CFG, github(pr),
                            [], {name: env}.get)
    assert out["run"] == "true" and out["review"] == name and out["head_ref"] == "reviewer/2026-10-14-project-fable"
    pending = [pr_json(50, "respond/pr49-2026-10-14")]
    out = G.resolve_respond("issue_comment", comment_event("/respond", number=49), {}, CFG,
                            github(pr, pending), [], {name: env}.get)
    assert out["run"] == "false" and "#50" in out["message"]
    other = pr_json(51, "reviewer/archive-cleanup")       # other reviewer/ branches are still ignored
    assert G.resolve_respond("issue_comment", comment_event("/respond", number=51), {}, CFG, github(other),
                             [], {name: env}.get) == G.skip("", pr="51")


def test_project_response_prompt_and_ids():
    env = env_with([finding(id="F1"), finding(id="F2")])
    env["review"]["scope"] = "project"
    system, user = RS.build_prompt(ROOT, CFG, env, ["F1", "F2"], 49, "main")
    assert "reviewed the project (not a single pull request)" in user and "git diff" not in user
    assert RS.row_prefix(LOG, "2026-10-14-project-fable.json") == "PROJ-2026-10-14"


# ---- review of project-review PRs; full decision-log text; diff without data files ----------------------------------

def test_decision_rows_keep_the_full_reason():
    env = env_with([finding(id="F1", title="x" * 120)])
    reason = ("A long reason. " * 40)[:600]                        # the schema's maximum
    row = RS.decision_rows([answer("F1", reason=reason, changes="y" * 300)], env, "r.json", "PR1", "d", "b")[0]
    assert "…" not in row and reason.strip() in row and "x" * 120 in row


def test_project_review_prs_can_be_reviewed_and_answered():
    pr = pr_json(49, "reviewer/2026-10-14-project-fable")
    out = G.resolve("issue_comment", comment_event("/review", number=49), {}, CFG, github(pr), [], TODAY)
    assert out["run"] == "true" and out["scope"] == "pr"           # reviews the fixes merged into it
    own = G.resolve("issue_comment", comment_event("/review", number=52), {}, CFG,
                    github(pr_json(52, "reviewer/archive-x")), [], TODAY)
    assert own["run"] == "false" and "reviewer's own output" in own["message"]   # no longer silent
    proj, later = env_with([finding()]), env_with([finding()])
    proj["review"]["scope"] = "project"
    later["meta"]["commit"] = pr["head"]["sha"]
    read = {"2026-10-14-project-fable.json": proj, "2026-10-14-pr49-fable.json": later}.get
    out = G.resolve_respond("issue_comment", comment_event("/respond", number=49), {}, CFG, github(pr),
                            ["reviews/2026-10-14-pr49-fable.json"], read)
    assert out["run"] == "true" and out["review"] == "2026-10-14-pr49-fable.json"   # the newer PR review wins


def test_reviewed_diff_leaves_out_data_files(tmp_path):
    assert C.pathspec_excludes(["data/raw/", "**/*.csv"]) == [":(exclude,glob)data/raw/**", ":(exclude,glob)**/*.csv"]

    def sh(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    sh("init", "-q", "-b", "main")
    sh("config", "user.email", "t@t")
    sh("config", "user.name", "t")
    (tmp_path / "m.py").write_text("x = 1\n")
    sh("add", "-A")
    sh("commit", "-qm", "base")
    sh("checkout", "-qb", "f")
    (tmp_path / "m.py").write_text("x = 2\n")
    (tmp_path / "backtests" / "v2" / "2026-10-14").mkdir(parents=True)
    (tmp_path / "backtests" / "v2" / "2026-10-14" / "big.csv").write_text("a,b\n" * 5000)
    sh("add", "-A")
    sh("commit", "-qm", "change")
    pack = C.build_pr_pack(tmp_path, CFG, "main", "f")
    assert "+x = 2" in pack["diff"] and "a,b" not in pack["diff"]
    assert "left out of this diff: backtests/v2/2026-10-14/big.csv" in pack["diff"]


def test_respond_workflow_records_the_fix_pr_number(tmp_path):
    """Runs the workflow's own sed line: 'Fixed in' must change from the branch name to the PR number."""
    text = (REPO / ".github" / "workflows" / "respond.yml").read_text()
    line = next(ln.strip() for ln in text.splitlines() if ln.strip().startswith("sed -i") and "decisions.md" in ln)
    command = line.split("   #")[0]                              # drop the trailing comment
    log = tmp_path / "reviews" / "decisions.md"
    log.parent.mkdir()
    log.write_text("| PR57-F1 | d | r | F1: t | fable | major | accept | why | respond/pr57-2026-10-15 |\n"
                   "| PR57-F2 | d | r | F2: t | fable | minor | reject | why | — |\n")
    subprocess.run(["bash", "-c", command], check=True, cwd=tmp_path,
                   env={"PATH": "/usr/bin:/bin", "BRANCH": "respond/pr57-2026-10-15", "num": "58"})
    out = log.read_text()
    assert "| #58 |" in out and "respond/pr57" not in out and "| — |" in out


# ---- Codex (ChatGPT subscription) reviewer, M6 ------------------------------------------------------------------------

from review_harness.providers import codex as CX  # noqa: E402

AUTH = {"auth_mode": "chatgpt", "tokens": {"access_token": "acc-" + "a" * 40, "refresh_token": "ref-" + "r" * 40,
                                           "id_token": "id-" + "i" * 40, "account_id": "acct-1"},
        "last_refresh": "2026-10-01T00:00:00Z"}

FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
home = os.environ["CODEX_HOME"]
auth = json.load(open(os.path.join(home, "auth.json")))
mode = "MODE_PLACEHOLDER"
open(os.path.join(home, "seen_args.json"), "w").write(json.dumps(args))
open(os.path.join(home, "seen_env.json"), "w").write(json.dumps(sorted(os.environ)))
prompt = "" if mode == "early" else sys.stdin.read()
open(os.path.join(home, "seen_prompt.txt"), "w").write(prompt)
def ev(e): print(json.dumps(e), flush=True)
ev({"type": "thread.started", "thread_id": "t1"})
ev({"type": "turn.started"})
if mode == "401":
    ev({"type": "error", "message": "Reconnecting... 1/5"})
    ev({"type": "turn.failed", "error": {"message": "unexpected status 401 Unauthorized: refresh token expired"}})
    sys.exit(1)
if mode == "early":
    sys.stderr.write("error: unexpected argument '--ephemeral' found\n")
    sys.exit(2)
if mode == "respond":                                         # the author edits the real checkout
    open("fix.txt", "w").write("the fix")
    open(os.path.join(os.environ["TMPDIR"], "t.txt"), "w").write("tmp is writable")
    ev({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
    open(args[args.index("-o") + 1], "w").write(json.dumps({"schema_version": 1, "summary": "1 accept",
        "responses": [{"finding_id": "F1", "decision": "accept", "reason": "r", "changes": "fix.txt"}],
        "tests": {"ran": True, "passed": True, "detail": "ok"}}))
    sys.exit(0)
open("scratch.txt", "w").write("written by the reviewer")    # lands in the disposable copy
open(os.path.join(os.environ["TMPDIR"], "t.txt"), "w").write("tmp is writable")
auth["tokens"]["access_token"] = "acc-" + "b" * 40            # simulate a refresh
auth["last_refresh"] = "2026-10-26T00:00:00Z"
json.dump(auth, open(os.path.join(home, "auth.json"), "w"))
ev({"type": "item.started", "item": {"id": "i1", "type": "command_execution", "command": "python -m pytest -q -p no:cacheprovider", "status": "in_progress"}})
ev({"type": "item.started", "item": {"id": "i2", "type": "reasoning", "text": "thinking"}})
ev({"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 800, "output_tokens": 50}})
schema = json.load(open(args[args.index("--output-schema") + 1]))
answer = {"schema_version": 1, "scope": "pr", "verdict": "approve_with_nits", "summary": "leaked " + auth["tokens"]["refresh_token"] + " and " + auth["tokens"]["access_token"],
          "findings": [{"id": "F1", "severity": "minor", "area": "code", "checklist_item": None, "title": "t",
                        "file": "README.md", "line_start": 3, "line_end": None, "claim": "c", "evidence": "e",
                        "proposed_change": "p", "verified_by": "ran_code", "confidence": 0.7, "related_decision": None}]}
open(args[args.index("-o") + 1], "w").write(json.dumps(answer))
'''


def fake_codex(tmp_path, mode="ok"):
    path = tmp_path / "codex"
    path.write_text(FAKE_CODEX.replace("MODE_PLACEHOLDER", mode))
    path.chmod(0o755)
    return str(path)


def codex_env_for(tmp_path, **extra):
    env = {"PATH": os.environ["PATH"], "CODEX_AUTH_JSON": json.dumps(AUTH), "GITHUB_TOKEN": "ghs_secret",
           "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-x", "CODEX_AUTH_OUT": str(tmp_path / "refreshed.json")}
    env.update(extra)
    return env


def test_strict_schema_requires_every_field_and_drops_unsupported_keywords():
    strict = CX.strict_schema(SCHEMA)
    f = strict["properties"]["findings"]["items"]
    assert set(f["required"]) == set(f["properties"]) and f["additionalProperties"] is False
    assert f["properties"]["line_start"]["type"] == ["integer", "null"]           # optional -> nullable
    assert f["properties"]["severity"]["type"] == "string" and None not in f["properties"]["severity"]["enum"]
    assert strict["properties"]["schema_version"] == {"enum": [1], "type": "integer"}
    text = json.dumps(strict)
    assert "$ref" not in text and "pattern" not in text and "maxLength" not in text and "$schema" not in text
    assert CX.strip_nulls({"a": None, "b": [{"c": None, "d": 1}]}) == {"b": [{"d": 1}]}


def test_codex_command_is_sandboxed_offline_and_never_asks():
    cmd = CX.build_command("codex", "gpt-6.1-sol", "high", "/s.json", "/o.json", "/w")
    assert cmd[:2] == ["codex", "exec"] and cmd[-1] == "-"
    assert cmd[cmd.index("-s") + 1] == "workspace-write" and "sandbox_workspace_write.network_access=false" in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-6.1-sol" and cmd[cmd.index("-C") + 1] == "/w"
    assert 'approval_policy="never"' in cmd and 'model_reasoning_effort="high"' in cmd and "--ephemeral" in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd and "danger-full-access" not in cmd
    assert "project_doc_max_bytes=0" in cmd                       # PR87-2-F1: AGENTS.md in the PR is not read
    assert 'web_search="cached"' in cmd                           # PR87-2-F2: cached search only, no live fetch


def test_codex_review_end_to_end_with_refresh_and_scrubbing(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    env = codex_env_for(tmp_path)
    p = CX.CodexProvider(CFG["reviewers"]["gpt"], cwd=ROOT, work_dir=work, binary=fake_codex(tmp_path), environ=env)
    steps = []
    p.on_step = steps.append
    c = p.complete("REVIEW RULES", [{"role": "user", "content": "the pack"}], 100)
    out = json.loads(c.text)
    assert out["summary"] == "leaked [redacted] and [redacted]" and "acc-bbbb" not in c.text   # incl. refreshed one
    assert not (work / "scratch.txt").exists()                        # the reviewer's writes stayed in the copy
    assert "line_end" not in out["findings"][0] and "related_decision" not in out["findings"][0]   # nulls dropped
    assert schema_errors(out, SCHEMA) == []
    assert (c.input_tokens, c.output_tokens) == (1000, 50) and steps == ["Run `python -m pytest -q -p no:cacheprovider`"]
    refreshed = json.loads((tmp_path / "refreshed.json").read_text())
    assert refreshed["tokens"]["access_token"] == "acc-" + "b" * 40 and p.auth == refreshed


def test_codex_environment_and_prompt(tmp_path, monkeypatch):
    seen = {}
    real = CX.CodexProvider._run

    def spy(self, cmd, prompt, env, current_secrets, cwd, budget):
        seen.update(env=env, prompt=prompt, cmd=cmd, cwd=cwd, budget=budget)
        return real(self, cmd, prompt, env, current_secrets, cwd, budget)
    monkeypatch.setattr(CX.CodexProvider, "_run", spy)
    p = CX.CodexProvider(CFG["reviewers"]["gpt"], cwd=ROOT, work_dir=tmp_path, binary=fake_codex(tmp_path),
                         environ=codex_env_for(tmp_path))
    p.complete("REVIEW RULES", [{"role": "user", "content": "the pack"}], 100)
    env = seen["env"]
    assert not {"GITHUB_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CODEX_AUTH_JSON", "CODEX_AUTH_OUT"} & set(env)
    assert env["CODEX_HOME"] == env["HOME"] and env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert seen["prompt"].startswith("# Instructions\n\nREVIEW RULES") and "disposable copy" in seen["prompt"]
    work = seen["cmd"][seen["cmd"].index("-C") + 1]                    # a copy, not the checkout itself
    assert work != str(tmp_path) and str(seen["cwd"]) == work and env["TMPDIR"] == work + "/.tmp"
    assert not Path(work).exists()                                    # thrown away after the run


def test_codex_failures_are_explained_and_login_kept(tmp_path):
    env = codex_env_for(tmp_path)
    p = CX.CodexProvider(CFG["reviewers"]["gpt"], cwd=ROOT, work_dir=tmp_path, binary=fake_codex(tmp_path, "401"),
                         environ=env)
    with pytest.raises(RuntimeError, match="Re-seed it: run `codex login`"):
        p.complete("s", [{"role": "user", "content": "u"}], 10)
    assert not (tmp_path / "refreshed.json").exists()                  # unchanged login is not written back
    assert "usage limit" in CX.explain(["429 Too Many Requests"], "", 1)
    with pytest.raises(RuntimeError, match="not set"):
        CX.CodexProvider(CFG["reviewers"]["gpt"], cwd=ROOT, binary=fake_codex(tmp_path), environ={"PATH": "/bin"})
    with pytest.raises(RuntimeError, match="not valid JSON"):
        CX.CodexProvider(CFG["reviewers"]["gpt"], cwd=ROOT, binary=fake_codex(tmp_path),
                         environ={"PATH": "/bin", "CODEX_AUTH_JSON": "abc\ndef"})


def test_gpt_reviewer_config_and_workflow_agree():
    gpt = get_reviewer(CFG, "gpt")
    assert gpt["provider"] == "codex" and gpt["secret"] == "CODEX_AUTH_JSON" and gpt["model"] == "gpt-6.1-sol"
    assert G.pr_target(CFG, pr_json(), "gpt", [], TODAY)["provider"] == "codex"
    wf = (REPO / ".github" / "workflows" / "review.yml").read_text()
    assert '"@openai/codex@${{ inputs.codex-version }}"' in wf
    assert yaml.safe_load(wf)[True]["workflow_call"]["inputs"]["codex-version"]["default"] == gpt["cli_version"]
    assert "secrets.CODEX_AUTH_JSON" in wf and "gh secret set CODEX_AUTH_JSON" in wf
    assert "secrets.SECRETS_WRITE_TOKEN" in wf


def test_timeout_kills_the_launcher_and_its_child(tmp_path):
    """npm launchers start the real CLI as a child; a timeout must stop both, or the output pipe never closes."""
    launcher = tmp_path / "launcher.sh"
    launcher.write_text("#!/bin/sh\nsleep 300 &\nwait\n")             # child keeps stdout open
    launcher.chmod(0o755)
    p = CX.CodexProvider(CFG["reviewers"]["gpt"], cwd=ROOT, work_dir=tmp_path, binary=str(launcher),
                         environ={"PATH": os.environ["PATH"], "CODEX_AUTH_JSON": json.dumps(AUTH)})
    p.timeout = 2
    import time
    t = time.time()
    with pytest.raises(RuntimeError, match="timed out"):
        p.complete("s", [{"role": "user", "content": "u"}], 10)
    assert time.time() - t < 20
    t = time.time()
    with pytest.raises(RuntimeError, match="timed out|without a result"):
        CCP.stream([str(launcher)], "p", tmp_path, {"PATH": os.environ["PATH"]}, 2)
    assert time.time() - t < 20


# ---- answers to the Fable review of #87 (PR87-F1..F9) ----------------------------------------------------------------

def test_review_step_holds_no_github_token_and_only_the_reviewers_secret():   # PR87-F1
    wf = (REPO / ".github" / "workflows" / "review.yml").read_text()
    step = wf[wf.index("      - name: Run the review"): wf.index("      - name: Save the refreshed Codex login")]
    assert 'GITHUB_TOKEN: ""' in step and 'GH_TOKEN: ""' in step and "secrets.GITHUB_TOKEN" not in step
    assert "needs.gate.outputs.provider == 'codex' && secrets.CODEX_AUTH_JSON" in step
    assert "needs.gate.outputs.provider == 'claude-code' && secrets.CLAUDE_CODE_OAUTH_TOKEN" in step
    assert "OPENAI_API_KEY" not in step and "GEMINI_API_KEY" not in step
    assert step.index("--unset-all http.https://github.com/.extraheader") < step.index("python -m review_harness.run")
    assert wf.index("Hand the progress-comment token") < wf.index("      - name: Run the review")
    for later in ("      - name: Open a PR with the project review", "      - name: Archive the review record"):
        block = wf[wf.index(later):]
        assert block.index("gh auth setup-git") < block.index(" push -q")


def test_progress_token_is_taken_from_a_file_and_the_file_removed(tmp_path):   # PR87-F1
    f = tmp_path / "progress_token"
    f.write_text("ghs_abc\n")
    p = PG.Progress("x", {"PROGRESS_TOKEN_FILE": str(f), "GITHUB_REPOSITORY": "o/r", "PROGRESS_PR": "1"})
    assert p.token == "ghs_abc" and p.enabled and not f.exists()
    assert PG.take_token({}) is None and PG.take_token({"PROGRESS_TOKEN_FILE": str(f)}) is None


def test_workspace_copy_has_no_git_credential(tmp_path):                        # PR87-F1, F2
    src = tmp_path / "src"
    src.mkdir()
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    subprocess.run(["git", "-C", str(src), "config", "--local", "http.https://github.com/.extraheader",
                    "AUTHORIZATION: basic secret"], check=True)
    (src / "a.py").write_text("x = 1\n")
    parent = tmp_path / "copy-parent"
    parent.mkdir()
    work = CX.make_workspace(src, parent)
    assert (work / "a.py").exists() and (work / ".tmp").is_dir()
    assert "extraheader" not in (work / ".git" / "config").read_text()
    assert "extraheader" in (src / ".git" / "config").read_text()      # the original is untouched
    (work / ".tmp" / "pytest-1").mkdir()
    status = subprocess.run(["git", "-C", str(work), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert ".tmp" not in status                                         # PR87-2-F7


def test_early_cli_exit_reports_its_stderr_not_a_broken_pipe(tmp_path):      # PR87-F4
    p = CX.CodexProvider(CFG["reviewers"]["gpt"], cwd=ROOT, work_dir=tmp_path, binary=fake_codex(tmp_path, "early"),
                         environ=codex_env_for(tmp_path))
    with pytest.raises(RuntimeError, match="unexpected argument '--ephemeral'"):
        p.complete("s", [{"role": "user", "content": "x" * 2_000_000}], 10)
    early = tmp_path / "early.sh"
    early.write_text("#!/bin/sh\necho 'bad flag --tools' >&2\nexit 2\n")
    early.chmod(0o755)
    with pytest.raises(RuntimeError, match="bad flag --tools"):
        CCP.stream([str(early)], "x" * 2_000_000, tmp_path, {"PATH": os.environ["PATH"]}, 30)


def test_gpt_runs_share_one_concurrency_group_and_refreshes_are_masked():     # PR87-F5, F3
    wf = (REPO / ".github" / "workflows" / "review.yml").read_text()
    # Every run on the Codex login, in either workflow, joins one queue; the group is set after the gate, from the
    # provider it chose, not from the comment text (PR87-2-F4, PR87-4-F2).
    group = ("needs.gate.outputs.codex == 'true' && 'cross-model-review-codex-login'")
    for name in ("review.yml", "respond.yml"):
        text = (REPO / ".github" / "workflows" / name).read_text()
        jobs = yaml.safe_load(text)["jobs"]
        assert "concurrency" not in yaml.safe_load(text), f"{name}: no workflow-level queue"
        work = [j for j in jobs.values() if j.get("needs") == "gate"]
        assert len(work) == 1 and group in work[0]["concurrency"]["group"], name
        assert work[0]["if"] == "needs.gate.outputs.run == 'true'"
        save = text[text.index("      - name: Save the refreshed Codex login"):]
        assert save.index("::add-mask::") < save.index("gh secret set")
    assert "comment.body, '/review gpt'" not in wf


def test_gate_reports_when_a_run_uses_the_codex_login():
    assert G.pr_target(CFG, pr_json(), "gpt", [], TODAY)["codex"] == "true"
    assert G.pr_target(CFG, pr_json(), "fable", [], TODAY)["codex"] == "false"
    assert G.pr_target(CFG, pr_json(ref="codex/x"), None, [], TODAY)["codex"] == "false"     # Opus reviews it


def test_failure_messages_match_codex_events_not_stray_stderr():              # PR87-F7
    generic = CX.explain([], "bash: warning: not a login shell; 4012 lines", 1)
    assert generic.startswith("Codex exited with 1")
    assert "Re-seed" in CX.explain(["unexpected status 401 Unauthorized"], "", 1)
    assert "usage limit" in CX.explain(["429 Too Many Requests"], "", 1)
    assert CX.explain(["401"], "", -9, timed_out=True).startswith("Codex timed out")


def test_codex_shares_kill_tree_and_has_its_own_time_limit(tmp_path):       # PR87-F6, F8
    assert CX.kill_tree is CCP.kill_tree
    p = CX.CodexProvider(CFG["reviewers"]["gpt"], cwd=ROOT, work_dir=tmp_path, binary=fake_codex(tmp_path),
                         environ=codex_env_for(tmp_path))
    assert p.timeout == 60 * CFG["limits"]["codex_timeout_minutes"]


def test_failure_is_diagnosed_from_the_last_failure_not_an_earlier_reconnect():   # PR87-2-F5
    assert CX.explain(["rate limit, reconnecting 1/5", "stream closed"], "", 1).startswith("Codex exited with 1")
    assert "usage limit" in CX.explain(["Reconnecting 1/5", "x"], "", 1, failed=["429 Too Many Requests"])
    assert "Re-seed" in CX.explain(["rate limit, reconnecting"], "", 1, failed=["401 Unauthorized"])


def test_half_written_login_file_keeps_the_real_failure_and_is_not_saved(tmp_path):   # PR87-2-F3
    out = tmp_path / "refreshed.json"
    p = CX.CodexProvider(CFG["reviewers"]["gpt"], cwd=ROOT, work_dir=tmp_path, binary=fake_codex(tmp_path, "ok"),
                         environ={**codex_env_for(tmp_path), "CODEX_AUTH_OUT": str(out)})
    auth = tmp_path / "auth.json"
    seeded = json.dumps(p.auth)
    auth.write_text('{"tokens": {')
    note = p._save_refreshed(auth, seeded)
    assert "half-written" in note and not out.exists() and json.dumps(p.auth) == seeded
    auth.write_text(seeded)
    assert p._save_refreshed(auth, seeded) == "" and not out.exists()


def test_claude_reviewer_web_searches_show_in_progress():
    assert CCP.describe("WebSearch", {"query": "credit gap data"}, ROOT) == "Search the web for `credit gap data`"


def test_respond_step_holds_no_github_token():                                    # PR87-3-F1
    wf = (REPO / ".github" / "workflows" / "respond.yml").read_text()
    step = wf[wf.index("      - name: Author answers the findings"): wf.index("      - name: Nothing to answer")]
    assert 'GITHUB_TOKEN: ""' in step and 'GH_TOKEN: ""' in step and "PROGRESS_TOKEN_FILE" in step
    assert step.index("--unset-all http.https://github.com/.extraheader") < step.index("python -m review_harness.respond")
    assert wf.index("Hand the progress-comment token") < wf.index("      - name: Author answers the findings")
    for later in ("      - name: Open the fix PR", "      - name: Archive the response record"):
        block = wf[wf.index(later):]
        assert block.index("gh auth setup-git") < block.index(" push -q")


def test_codex_web_searches_show_their_query():                                   # PR87-3-F2
    assert CX.describe({"type": "web_search", "query": "loan  default\nrates"}) == "Search the web for `loan default rates`"
    assert CX.describe({"type": "web_search"}) == "Search the web"


def test_no_github_token_or_credential_while_pr_requirements_install():            # PR87-4-F1
    wf = (REPO / ".github" / "workflows" / "review.yml").read_text()
    unset = wf.index("      - name: Remove the checkout's git credential before any PR code runs")
    assert wf.index("      - name: Check out the PR") < unset < wf.index("          ${{ inputs.install }}")
    for name in ("      - name: Install Claude Code and the repo's", "      - name: Install the Codex CLI"):
        block = wf[wf.index(name):]
        block = block[:block.index("${{ inputs.install }}")]
        assert 'GITHUB_TOKEN: ""' in block and 'GH_TOKEN: ""' in block
    rf = (REPO / ".github" / "workflows" / "respond.yml").read_text()
    assert rf.index("--unset-all http.https://github.com/.extraheader") < rf.index("${{ inputs.install }}")
    block = rf[rf.index("      - name: Install the author's CLI and the PR's dependencies"):]
    assert 'GITHUB_TOKEN: ""' in block[:block.index("${{ inputs.install }}")]


def test_codex_time_budget_is_shared_by_the_retry(tmp_path):                        # PR87-4-F3
    launcher = tmp_path / "hang.sh"
    launcher.write_text("#!/bin/sh\nsleep 300 &\nwait\n")
    launcher.chmod(0o755)
    p = CX.CodexProvider(CFG["reviewers"]["gpt"], cwd=ROOT, work_dir=tmp_path, binary=str(launcher),
                         environ={"PATH": os.environ["PATH"], "CODEX_AUTH_JSON": json.dumps(AUTH)})
    p.timeout = 2
    import time
    t = time.time()
    with pytest.raises(RuntimeError, match="timed out"):
        p.complete("s", [{"role": "user", "content": "u"}], 10)
    with pytest.raises(RuntimeError, match="budget"):               # the retry gets no fresh 2 s
        p.complete("s", [{"role": "user", "content": "u"}], 10)
    assert time.time() - t < 10


def test_codex_sandbox_is_enabled_and_checked_before_the_review():
    """The first live GPT review could run no commands: Ubuntu 24.04 runners block the user namespaces Codex's
    bubblewrap sandbox needs."""
    wf = (REPO / ".github" / "workflows" / "review.yml").read_text()
    step = wf[wf.index("      - name: Let Codex's sandbox start"): wf.index("      - name: Run the review")]
    assert "needs.gate.outputs.provider == 'codex'" in step and 'GITHUB_TOKEN: ""' in step
    assert "sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0" in step
    assert step.index("sysctl") < step.index("codex sandbox")
    assert "sandbox_workspace_write.network_access=false" in step and "::warning::" in step


@pytest.mark.parametrize("workflow", ["review.yml", "respond.yml"])
def test_every_workflow_script_is_valid_bash(workflow, tmp_path):
    """A stray quote in respond.yml (added with PR87-4-F1) broke every /respond with a bash syntax error that the
    text-based workflow tests could not see. Parse each step's script with `bash -n`."""
    import re
    import yaml
    wf = yaml.safe_load((REPO / ".github" / "workflows" / workflow).read_text())
    checked = 0
    for job in wf["jobs"].values():
        for step in job["steps"]:
            if "run" not in step:
                continue
            script = re.sub(r"\$\{\{.*?\}\}", "x", step["run"], flags=re.S)
            f = tmp_path / "step.sh"
            f.write_text(script)
            r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
            assert r.returncode == 0, f"{workflow} / {step.get('name', '?')}: {r.stderr}"
            checked += 1
    assert checked >= 8


def test_codex_as_author_edits_the_checkout_in_place_without_web(tmp_path):
    work = tmp_path / "pr"
    work.mkdir()
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    seen = tmp_path / "seen"
    p = CX.CodexProvider(CFG["authors"]["codex"], cwd=ROOT, work_dir=work, binary=fake_codex(tmp_path, "respond"),
                         environ=codex_env_for(tmp_path, RUNNER_TEMP=str(seen.parent)), mode="respond",
                         schema=RESP_SCHEMA)
    homes = []
    real = CX.CodexProvider._run

    def spy(self, cmd, prompt, env, current_secrets, cwd, budget):
        homes.append((cmd, prompt, env, cwd))
        return real(self, cmd, prompt, env, current_secrets, cwd, budget)
    import unittest.mock
    with unittest.mock.patch.object(CX.CodexProvider, "_run", spy):
        out = json.loads(p.complete("s", [{"role": "user", "content": "u"}], 10).text)
    assert out["responses"][0]["decision"] == "accept"
    assert (work / "fix.txt").read_text() == "the fix"                   # the edit stays in the PR checkout
    cmd, prompt, env, cwd = homes[0]
    assert cwd == work and cmd[cmd.index("-C") + 1] == str(work)
    assert 'web_search="disabled"' in cmd and 'web_search="cached"' not in cmd   # the author gets no web tools
    tmp = Path(env["TMPDIR"])
    assert work not in tmp.parents and cmd[cmd.index("--add-dir") + 1] == str(tmp)
    assert "cannot commit or push" in prompt and "disposable copy" not in prompt
    assert p.timeout == 60 * CFG["limits"]["respond_codex_timeout_minutes"]
    with pytest.raises(ValueError):
        CX.build_command("codex", "m", None, "s", "o", "w", mode="anything")


def test_respond_uses_the_prs_author(monkeypatch, tmp_path):
    seen = {}

    class Stop(Exception):
        pass

    def fake_codex_provider(author, **kw):
        seen.update(author=author, **kw)
        raise Stop
    monkeypatch.setattr("review_harness.providers.codex.CodexProvider", fake_codex_provider)
    review = tmp_path / "r.json"
    review.write_text("{}")
    with pytest.raises(Stop):
        RS.main(["--work-dir", str(tmp_path), "--review-file", str(review), "--fixed-in", "b",
                 "--summary-out", str(tmp_path / "s.md"), "--author", "codex"])
    assert seen["author"]["model"] == CFG["authors"]["codex"]["model"] and seen["mode"] == "respond"


def test_gate_answers_with_the_prs_author():
    env = {"meta": {"commit": "abc123", "reviewer": "opus", "model": "claude-opus-5-5"},
           "review": {"scope": "pr", "findings": [{"id": "F1"}]}}

    def get(path):
        return [] if path.startswith("pulls?") else pr_json(ref="codex/add-x")
    out = G.resolve_respond("issue_comment", comment_event("/respond"), {}, CFG, get,
                            [f"reviews/{TODAY}-pr7-opus.json"], lambda n: env)
    assert out["run"] == "true" and out["author"] == "codex" and out["codex"] == "true"
    get2 = lambda path: [] if path.startswith("pulls?") else pr_json()     # noqa: E731
    out = G.resolve_respond("issue_comment", comment_event("/respond"), {}, CFG, get2,
                            [f"reviews/{TODAY}-pr7-gpt.json"], lambda n: env)
    assert out["author"] == "claude" and out["codex"] == "false"


def test_codex_fix_prs_keep_codex_as_the_author():                                  # PR93-F1
    from review_harness.config import author_for
    env = {"meta": {"commit": "abc123", "reviewer": "opus", "model": "claude-opus-5-5"},
           "review": {"scope": "pr", "findings": [{"id": "F1"}]}}
    get = lambda path: [] if path.startswith("pulls?") else pr_json(ref="codex/add-x")   # noqa: E731
    out = G.resolve_respond("issue_comment", comment_event("/respond"), {}, CFG, get,
                            [f"reviews/{TODAY}-pr7-opus.json"], lambda n: env)
    assert out["author"] == "codex" and out["fix_prefix"] == "respond/codex/"
    fix = pr_json(8, ref=f"respond/codex/pr7-{TODAY}")              # the fix PR the workflow then opens
    assert author_for(CFG, fix["head"]["ref"])["name"] == "codex"
    review = G.pr_target(CFG, fix, None, [], TODAY)
    assert review["reviewer"] == "opus" and review["author"] == "codex"
    assert "built this work" in G.pr_target(CFG, fix, "gpt", [], TODAY)["message"]
    get2 = lambda path: [] if path.startswith("pulls?") else fix    # noqa: E731
    again = G.resolve_respond("issue_comment", comment_event("/respond", number=8), {}, CFG, get2,
                              [f"reviews/{TODAY}-pr8-opus.json"], lambda n: env)
    assert again["author"] == "codex"
    # Claude's fix PRs keep the old names and stay Claude's.
    claude = G.resolve_respond("issue_comment", comment_event("/respond"), {}, CFG,
                               lambda path: [] if path.startswith("pulls?") else pr_json(),
                               [f"reviews/{TODAY}-pr7-gpt.json"], lambda n: env)
    assert claude["fix_prefix"] == "respond/" and author_for(CFG, f"respond/pr7-{TODAY}")["name"] == "claude"


@pytest.mark.parametrize("ref, pending", [("respond/pr7-2026-10-26", True), ("respond/codex/pr7-2026-10-26", True),
                                          ("respond/codex/pr70-2026-10-26", False), ("respond/pr70-x", False)])
def test_pending_fix_prs_are_found_for_either_author(ref, pending):
    env = {"meta": {"commit": "abc123"}, "review": {"scope": "pr", "findings": [{"id": "F1"}]}}
    get = lambda path: [pr_json(50, ref)] if path.startswith("pulls?") else pr_json()     # noqa: E731
    out = G.resolve_respond("issue_comment", comment_event("/respond"), {}, CFG, get,
                            [f"reviews/{TODAY}-pr7-gpt.json"], lambda n: env)
    assert (out["run"] == "false" and "still open" in out["message"]) is pending


def test_respond_is_checked_again_after_the_queue():                                # PR93-F2
    fresh = {"run": "true", "pr": "7", "review": "r.json", "head_sha": "abc", "author": "codex"}
    expected = {"pr": "7", "review": "r.json", "head_sha": "abc", "author": "codex"}
    assert G.recheck_respond(dict(fresh), expected)["run"] == "true"
    moved = G.recheck_respond(dict(fresh, head_sha="def"), expected)
    assert moved["run"] == "false" and "head_sha" in moved["message"]
    opened = G.skip("The author's fix PR for #7 (#9) is still open", pr="7")       # another response got there first
    assert G.recheck_respond(opened, expected) == opened
    wf = (REPO / ".github" / "workflows" / "respond.yml").read_text()
    job = yaml.safe_load(wf)["jobs"]["respond"]
    names = [s.get("name", "") for s in job["steps"]]
    recheck = names.index("Check again now that this job holds the queue")
    assert recheck < names.index("Check out the PR in a separate work tree")
    assert "--respond --recheck" in job["steps"][recheck]["run"]
    for s in job["steps"][recheck + 2:]:
        if s.get("name") in ("Check out the PR in a separate work tree", "Install the author's CLI and the PR's dependencies",
                             "Hand the progress-comment token to the harness in a file", "Author answers the findings"):
            assert "steps.recheck.outputs.run == 'true'" in s["if"], s["name"]
    work = job["steps"][names.index("Check out the PR in a separate work tree")]["run"]
    assert '"$(git rev-parse pr-head)" != "$HEAD_SHA"' in work and "${FIX_PREFIX}pr$PR" in work


def test_label_is_removed_whether_or_not_a_review_runs():                            # PR93-2-F1
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "review.yml").read_text())
    gate = {s.get("name"): s for s in wf["jobs"]["gate"]["steps"]}
    step = gate["Remove the label when no review follows"]
    assert "always()" in step["if"] and "steps.gate.outputs.run != 'true'" in step["if"]
    assert "github.event.label.name == inputs.label" in step["if"] and "labels/$LABEL" in step["run"]
    review = {s.get("name"): s for s in wf["jobs"]["review"]["steps"]}
    assert "always()" in review["Remove the label so it can be added again"]["if"]     # after a review that ran
    assert CFG["triggers"]["pr_label"] == "review"


# ---- harness fixes from project review 2026-10-26-project-gpt-2 ------------------------------------------------------

def _valid_review():
    return {"schema_version": 1, "scope": "project", "verdict": "attention", "summary": "s",
            "findings": [finding(id="F1")]}


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(findings=None),
    lambda r: r.update(findings=[1]),
    lambda r: r["findings"][0].update(line_start="3", line_end=4),
    lambda r: r["findings"][0].update(file=None),
    lambda r: r.update(findings=[None]),
])
def test_schema_invalid_replies_reach_the_retry(mutate):                           # PROJ-2026-10-26-F2
    bad = _valid_review()
    mutate(bad)
    review, errors = R.check(json.dumps(bad), "project", SCHEMA, ROOT)
    assert errors                                                       # reported, not raised

    pack = dict(PACK, scope="project")
    ok = R.run_review(ROOT, CFG, REVIEWER, FakeProvider([json.dumps(bad), json.dumps(_valid_review())]), pack)
    assert "invalid" not in ok["meta"] and ok["meta"]["attempts"] == 2
    twice = R.run_review(ROOT, CFG, REVIEWER, FakeProvider([json.dumps(bad), json.dumps(bad)]), pack)
    assert twice["meta"]["invalid"] and twice["meta"]["attempts"] == 2


def _repo(tmp_path):
    work = tmp_path / "repo"
    (work / "review").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    (work / "review" / "config.yaml").write_text("a: 1\n")
    (work / "notes.md").write_text("n\n")
    for cmd in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(work), *cmd], check=True)
    return work


def _git(work, *args):
    subprocess.run(["git", "-C", str(work), *args], check=True, capture_output=True)


def test_rollback_undoes_renames_out_of_and_into_protected_paths(tmp_path):           # PROJ-2026-10-26-F5
    work = _repo(tmp_path)
    _git(work, "mv", "review/config.yaml", "moved.yaml")                 # out of a protected folder
    assert set(RS.revert_protected(work, ["review/"])) == {"review/config.yaml", "moved.yaml"}
    assert (work / "review" / "config.yaml").read_text() == "a: 1\n" and not (work / "moved.yaml").exists()
    _git(work, "mv", "notes.md", "review/notes.md")                       # into one
    RS.revert_protected(work, ["review/"])
    assert (work / "notes.md").exists() and not (work / "review" / "notes.md").exists()
    (work / "review" / "new.yaml").write_text("x")                        # a staged addition
    _git(work, "add", "review/new.yaml")
    assert RS.revert_protected(work, ["review/"]) == ["review/new.yaml"] and not (work / "review" / "new.yaml").exists()
    (work / "notes.md").write_text("edited\n")                           # ordinary edits stay
    assert RS.revert_protected(work, ["review/"]) == [] and (work / "notes.md").read_text() == "edited\n"
    status = subprocess.run(["git", "-C", str(work), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert status.strip() == "M notes.md"


def test_dependents_follow_package_relative_and_aliased_imports(tmp_path):         # PROJ-2026-10-26-F4
    from review_harness.context import find_dependents
    files = {
        "pkg/__init__.py": "", "pkg/core.py": "def f(): pass\n",
        "pkg/sibling.py": "from .core import f\n",                      # relative
        "pkg/script.py": "import core\n",                               # bare sibling import
        "a.py": "from pkg import core as c\nc.f()\n",                   # package import with alias
        "b.py": "import pkg.core\n",                                    # dotted import
        "other/__init__.py": "", "other/core.py": "x = 1\n",
        "c.py": "from other import core\n",                             # same stem, different package
        "d.py": "import json, core_utils\n",                            # look-alike names
        "tests/test_x.py": "from pkg.core import f\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    found = find_dependents(tmp_path, ["pkg/core.py"])
    assert set(found) == {"pkg/sibling.py", "pkg/script.py", "a.py", "b.py", "tests/test_x.py"}
    assert "tests/test_review_harness.py" in find_dependents(REPO, ["review_harness/context.py"])
    assert not [f for f in find_dependents(REPO, ["review_harness/run.py"]) if f.startswith("tests/fixture/")]


def test_pr_pack_and_checks_use_the_prs_own_revision(tmp_path):                       # PROJ-2026-10-26-F1
    """A PR that changes the harness is reviewed against its own code, while the decision log comes from main."""
    import shutil
    main = tmp_path / "main"
    (main / "scripts" / "review_harness").mkdir(parents=True)
    (main / "reviews").mkdir()
    (main / "scripts" / "review_harness" / "thing.py").write_text('value = "old"\n')
    (main / "reviews" / "decisions.md").write_text("main log\n")
    (main / "README.md").write_text("r\n")
    g = ["-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(main)], check=True)
    subprocess.run(["git", "-C", str(main), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(main), *g, "commit", "-qm", "base"], check=True)
    pr = tmp_path / "pr"
    shutil.copytree(main, pr)
    subprocess.run(["git", "-C", str(pr), "checkout", "-qb", "feature"], check=True)
    (pr / "scripts" / "review_harness" / "thing.py").write_text('value = "new"\n')
    (pr / "reviews" / "decisions.md").write_text("rewritten by the PR\n")
    (pr / "added.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(pr), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(pr), *g, "commit", "-qm", "change"], check=True)
    cfg = copy.deepcopy(CFG)
    cfg["context"]["pr"]["always"] = ["reviews/decisions.md"]
    pack = C.build_pr_pack(pr, cfg, "main", "feature", trusted=main)
    full = pack["text"].split("===== scripts/review_harness/thing.py =====")[1]
    assert '+value = "new"' in pack["diff"] and full.lstrip().startswith('value = "new"')    # one revision
    assert "main log" in pack["text"] and "===== reviews/decisions.md =====\nrewritten" not in pack["text"]
    good = review(findings=[finding(file="added.py")])                  # a file only the PR has
    assert R.check(json.dumps(good), "pr", SCHEMA, pr)[1] == []
    assert R.check(json.dumps(good), "pr", SCHEMA, main)[1]


# ---- fixes from project review 2026-10-26-project-gpt-3 -------------------------------------------------------------

def _env(scope="pr", pr=7, commit="abc123", invalid=False):
    e = {"meta": {"commit": commit, "pr": pr if scope == "pr" else None, "reviewer": "gpt", "model": "gpt-6.1-sol"},
         "review": None if invalid else {"scope": scope, "findings": [{"id": "F1"}]}}
    if invalid:
        e["meta"]["invalid"] = ["x"]
    return e


def test_respond_answers_only_reviews_of_this_pr():                                   # PROJ-2026-10-26-2-F1
    get = lambda path: [] if path.startswith("pulls?") else pr_json()               # noqa: E731
    named = lambda body, env: G.resolve_respond("issue_comment", comment_event(body), {}, CFG, get, [],  # noqa: E731
                                                lambda n: env)
    project = named("/respond 2026-10-14-project-fable.json", _env("project"))
    assert project["run"] == "false" and "project review" in project["message"]
    other = named(f"/respond {TODAY}-pr70-gpt.json", _env(pr=70))
    assert other["run"] == "false" and "#70, not #7" in other["message"]
    assert named(f"/respond {TODAY}-pr7-gpt.json", _env())["run"] == "true"         # its own review: fine
    # A project review is still answered on the PR that carries it.
    carrier = pr_json(96, "reviewer/2026-10-26-project-gpt-3")
    out = G.resolve_respond("issue_comment", comment_event("/respond", number=96), {}, CFG,
                            lambda path: [] if path.startswith("pulls?") else carrier, [],
                            lambda n: _env("project"))
    assert out["run"] == "true" and out["review"] == "2026-10-26-project-gpt-3.json"


def test_a_failed_review_attempt_does_not_block_a_new_review():                      # PROJ-2026-10-26-2-F3
    newest = [f"reviews/{TODAY}-pr7-gpt-2.json", f"reviews/{TODAY}-pr7-gpt.json"]
    records = {f"{TODAY}-pr7-gpt-2.json": _env(invalid=True), f"{TODAY}-pr7-gpt.json": _env(commit="old999")}
    last = G.last_valid_review(newest, 7, records.get)
    assert last == (f"{TODAY}-pr7-gpt.json", "old999")                             # the failed attempt is skipped
    out = G.resolve("issue_comment", comment_event("/review"), {}, CFG, lambda p: pr_json(), [], TODAY,
                    lambda n: G.last_valid_review(newest, n, records.get))
    assert out["run"] == "true"                                                     # same commit as the failure
    records[f"{TODAY}-pr7-gpt.json"] = _env()                                       # a valid review of abc123
    out = G.resolve("issue_comment", comment_event("/review"), {}, CFG, lambda p: pr_json(), [], TODAY,
                    lambda n: G.last_valid_review(newest, n, records.get))
    assert out["run"] == "false" and "already reviewed" in out["message"]


def test_claude_code_shares_one_time_budget_with_its_retry(monkeypatch):             # PROJ-2026-10-26-2-F2
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
    seen = []

    def fake_run(cmd, **kw):
        seen.append(kw["timeout"])
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": "{}", "usage": {}}), "")
    p = CCP.ClaudeCodeProvider(CFG["reviewers"]["fable"], run=fake_run)
    clock = [1000.0]
    monkeypatch.setattr(CCP.time, "monotonic", lambda: clock[0])
    p.complete("s", [{"role": "user", "content": "u"}], 10)
    clock[0] += 20 * 60                                                             # the first attempt took 20 min
    p.complete("s", [{"role": "user", "content": "u"}], 10)
    assert seen == [1500, 300]                                                      # 25 minutes in all
    clock[0] += 5 * 60 - 30
    with pytest.raises(RuntimeError, match="budget"):
        p.complete("s", [{"role": "user", "content": "u"}], 10)


def test_changed_package_initialiser_brings_its_importers():                         # PROJ-2026-10-26-2-F4
    from review_harness.context import find_dependents
    assert "review_harness/run.py" in find_dependents(REPO, ["review_harness/providers/__init__.py"])


# ---- shared-harness settings --------------------------------------------------------------------------------------

def test_project_root_comes_from_the_environment_and_schemas_from_the_package():
    from review_harness import config
    assert config.ROOT == ROOT.resolve()                                 # conftest sets REVIEW_PROJECT_ROOT
    assert config.schema_path(ROOT, {}) == REPO / "review_harness" / "schemas" / "review.json"
    assert config.schema_path(ROOT, {"output_schema": "x.json"}) == ROOT / "x.json"
    assert config.author_schema_path(ROOT, {}).name == "respond.json"


def test_protected_paths_cover_the_review_files_plus_extras():
    from review_harness.config import protected_paths
    base = protected_paths({"instructions": "REVIEW.md", "decision_log": "reviews/decisions.md"})
    assert base == [".github/", "review/", "reviews/", "REVIEW.md"]
    extra = protected_paths({"instructions": "docs/REVIEWER.md", "decision_log": "logs/decisions.md",
                             "protected": ["scripts/build.py", "review/"]})
    assert extra == [".github/", "review/", "logs/", "docs/REVIEWER.md", "scripts/build.py"]
    cmd = CCP.build_command("m", "s", RESP_SCHEMA, 1, mode="respond", protected=extra)
    assert "Edit(./docs/REVIEWER.md)" in cmd and "Write(./scripts/build.py)" in cmd


def test_footer_is_optional():
    from review_harness.config import footer
    assert footer({}) == "" and footer(CFG).startswith("_Research")


def test_review_on_open_is_opt_in_and_skips_drafts():
    opened = {"action": "opened", "pull_request": {"number": 7, "draft": False}}
    assert G.resolve("pull_request", opened, {}, CFG, lambda p: pr_json(), [], TODAY)["run"] == "false"   # off
    on = copy.deepcopy(CFG)
    on["triggers"]["review_on_open"] = True
    out = G.resolve("pull_request", opened, {}, on, lambda p: pr_json(), [], TODAY)
    assert out["run"] == "true" and out["reviewer"] == "gpt"                   # the author's default reviewer
    draft = {"action": "opened", "pull_request": {"number": 7, "draft": True}}
    assert G.resolve("pull_request", draft, {}, on, lambda p: pr_json(), [], TODAY)["run"] == "false"
    ready = {"action": "ready_for_review", "pull_request": {"number": 7, "draft": False}}
    assert G.resolve("pull_request", ready, {}, on, lambda p: pr_json(ref="codex/x"), [], TODAY)["reviewer"] == "opus"


def test_agent_env_reaches_reviewers_but_never_credentials(tmp_path):
    from review_harness.config import agent_env_extra
    cfg = dict(CFG, agent_env={"TRADELAB_PROVIDER": "synthetic"})
    assert agent_env_extra(cfg) == {"TRADELAB_PROVIDER": "synthetic"}
    for bad in ({"GH_TOKEN": "x"}, {"OPENAI_API_KEY": "x"}, {"lower": "x"}, {"1X": "x"}):
        with pytest.raises(ValueError):
            agent_env_extra(dict(CFG, agent_env=bad))
    env = CCP.agent_env("CLAUDE_CODE_OAUTH_TOKEN", {"PATH": "/bin", "CLAUDE_CODE_OAUTH_TOKEN": "t"},
                        agent_env_extra(cfg))
    assert env["TRADELAB_PROVIDER"] == "synthetic"
    cx = CX.codex_env(tmp_path, tmp_path, {"PATH": "/bin"}, agent_env_extra(cfg))
    assert cx["TRADELAB_PROVIDER"] == "synthetic"


def test_scoped_branches_limit_what_the_author_may_change(tmp_path):
    from review_harness.config import scope_for
    cfg = dict(CFG, scopes=[{"branch_prefixes": ["research/"], "allowed": ["strategies/[!_]*/card.yaml", "notes.md"]}])
    assert scope_for(cfg, "research/week-1") == ["strategies/[!_]*/card.yaml", "notes.md"]
    assert scope_for(cfg, "feat/x") is None and scope_for(cfg, None) is None
    work = _repo(tmp_path)                                                   # review/config.yaml + notes.md
    (work / "strategies" / "a").mkdir(parents=True)
    (work / "strategies" / "a" / "card.yaml").write_text("x")
    (work / "engine.py").write_text("y")
    (work / "notes.md").write_text("edited\n")
    reverted = RS.revert_protected(work, ["review/"], scope_for(cfg, "research/week-1"))
    assert sorted(reverted) == ["engine.py"]                                # outside the scope: undone
    assert (work / "strategies" / "a" / "card.yaml").exists() and (work / "notes.md").read_text() == "edited\n"


def test_respond_workflow_checks_the_authors_changes_without_a_token():
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "respond.yml").read_text())
    steps = {s.get("name"): s for s in wf["jobs"]["respond"]["steps"]}
    check = steps["Check the author's changes"]
    assert check["env"]["GITHUB_TOKEN"] == "" and check["env"]["GH_TOKEN"] == ""
    assert "git checkout -q -- . && git clean -fdq" in check["run"] and "summary.md" in check["run"]
    names = list(steps)
    assert names.index("Author answers the findings") < names.index("Check the author's changes") \
        < names.index("Open the fix PR into the reviewed PR's branch")
    assert '--head-ref "$HEAD_REF"' in steps["Author answers the findings"]["run"]


def test_protected_globs_are_undone_too(tmp_path):
    work = _repo(tmp_path)
    (work / "strategies" / "a" / "results").mkdir(parents=True)
    (work / "strategies" / "a" / "results" / "report.md").write_text("hand edit")
    (work / "strategies" / "a" / "card.yaml").write_text("ok")
    assert RS.revert_protected(work, ["review/", "strategies/*/results/"]) == ["strategies/a/results/report.md"]
    assert (work / "strategies" / "a" / "card.yaml").exists()


def test_only_the_review_process_files_come_from_main(tmp_path):
    cfg = dict(CFG, protected=["docs/METHODOLOGY.md"])
    assert C.always_source("reviews/decisions.md", tmp_path, ROOT, cfg) == ROOT
    assert C.always_source("docs/METHODOLOGY.md", tmp_path, ROOT, cfg) == tmp_path   # the PR's version


def test_missing_settings_on_main_give_a_message_not_a_crash():
    out = G.not_set_up({"issue": {"number": 30}}, {})
    assert out["run"] == "false" and out["pr"] == "30" and "review/config.yaml" in out["message"]
    assert G.not_set_up({"pull_request": {"number": 5}}, {})["pr"] == "5"
    assert G.not_set_up({}, {"pr": "9"})["pr"] == "9" and G.not_set_up({}, {})["pr"] == ""
