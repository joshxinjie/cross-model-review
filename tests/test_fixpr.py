"""Fix PR status and verification (plan v3 A2): only the check's own exit code 0 opens a normal PR; failed, not
configured, unfinished and unknown open a draft with the reason first; the author's verification gaps stay visible."""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from review_harness import fixpr as F
from review_harness import respond as RS
from review_harness.providers import codex as CX

REPO = Path(__file__).resolve().parents[1]
WF = yaml.safe_load((REPO / ".github" / "workflows" / "respond.yml").read_text())
STEPS = {s.get("name"): s for s in WF["jobs"]["respond"]["steps"]}
RESP_SCHEMA = json.loads((REPO / "review_harness" / "schemas" / "respond.json").read_text())


# ---- the decision ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("configured, code, draft, state", [
    (True, "0", False, "passed"),
    (True, "1", True, "failed"),
    (True, "137", True, "failed"),            # killed by a signal: a code, and not 0
    (True, "", True, "unknown"),              # configured, but no exit code was recorded (did not finish)
    (True, None, True, "unknown"),
    (True, "0\n", False, "passed"),
    (True, "abc", True, "unknown"),
    (True, "-1", True, "unknown"),
    (False, "", True, "not_configured"),
    (False, "0", True, "not_configured"),     # a stray code without a configured check proves nothing
])
def test_only_exit_code_zero_opens_a_normal_pr(configured, code, draft, state):
    s = F.check_status(configured, code)
    assert (s["draft"], s["state"]) == (draft, state)
    assert ("draft" in s["headline"].lower()) == draft


def test_a_check_that_did_not_pass_leads_the_description():
    summary = "### Author response\nall accepted\n"
    failed = F.compose(summary, F.check_status(True, "2"), "E   assert 1 == 2\n", "a" * 40)
    assert failed.index("Configured checks failed") < failed.index("### Author response")
    assert "assert 1 == 2" in failed and "`aaaaaaaaaaaa`" in failed
    passed = F.compose(summary, F.check_status(True, "0"), "25 passed\n", "a" * 40)
    assert passed.index("### Author response") < passed.index("Configured checks passed")
    none = F.compose(summary, F.check_status(False, ""), None)
    assert none.startswith("**⚠️ No configured check ran**") and "Check output" not in none
    long = F.compose(summary, F.check_status(True, "1"), "\n".join(f"line {i}" for i in range(500)) + "\n```\n")
    assert "line 499" in long and "line 400" not in long and long.count("```") == 2


# ---- the workflow ------------------------------------------------------------------------------------------------------

def run_step(script: str, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-e", "-c", script], cwd=cwd, env={**os.environ, **env}, capture_output=True,
                          text=True)


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def runner(tmp_path):
    """RUNNER_TEMP with a work tree whose origin is a local bare repo, a trusted main checkout, a fake gh."""
    temp, remote, ws, bin_ = tmp_path / "temp", tmp_path / "remote.git", tmp_path / "ws", tmp_path / "bin"
    for d in (temp, ws, bin_):
        d.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    work = temp / "work"
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    git(work, "config", "user.email", "t@t")
    git(work, "config", "user.name", "t")
    (work / "reviews").mkdir()
    (work / "reviews" / "decisions.md").write_text("| PR7-F1 | x | respond/pr7 |\n")
    (work / "a.py").write_text("x = 1\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    git(work, "push", "-q", "origin", "HEAD:main")
    git(work, "checkout", "-q", "-b", "respond/pr7")
    (work / "a.py").write_text("x = 2\n")                      # the author's change
    (work / "review_harness").mkdir()                          # a PR that tries to shadow the harness
    (work / "review_harness" / "__init__.py").write_text("")
    (work / "review_harness" / "fixpr.py").write_text("print('draft=false')\n")
    (temp / "summary.md").write_text("### Author response\nsummary\n")
    calls = tmp_path / "gh_calls.txt"
    gh = bin_ / "gh"
    gh.write_text(f"""#!/bin/bash
echo "$*" >> {calls}
if [ "$1" = auth ]; then exit 0; fi
if [ "$1" = api ] && [[ "$2" == */pulls ]]; then
  if [[ "$*" == *"draft=true"* ]] && [ -n "$GH_NO_DRAFT" ]; then
    echo '{{"message":"Draft pull requests are not supported in this repository."}}' >&2; exit 1
  fi
  echo "https://github.com/o/r/pull/42"; exit 0
fi
exit 0
""")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    env = {"RUNNER_TEMP": str(temp), "GITHUB_WORKSPACE": str(ws), "GITHUB_OUTPUT": str(tmp_path / "out.txt"),
           "GITHUB_REPOSITORY": "o/r", "PATH": f"{bin_}:{os.environ['PATH']}",
           "PYTHONPATH": str(REPO), "PR": "7", "HEAD_REF": "feature", "REVIEW": "2026-11-01-pr7-gpt.json",
           "BRANCH": "respond/pr7"}
    return {"temp": temp, "work": work, "env": env, "calls": calls, "out": tmp_path / "out.txt", "ws": ws}


def check_step(runner, check):
    return run_step(STEPS["Check the author's changes"]["run"],
                    dict(runner["env"], CHECK=check, PR_TITLE="t", BASE="main"), runner["work"])


def test_check_step_exports_the_check_exit_code_and_still_succeeds(runner):
    for check, code in (("true", "0"), ("echo boom; exit 3", "3"), ("kill -9 $$", "137")):
        runner["out"].write_text("")
        r = check_step(runner, check)
        assert r.returncode == 0, r.stderr                     # the step's outcome is not the check's result
        assert runner["out"].read_text().strip() == f"code={code}", check
    assert "boom" not in (runner["temp"] / "summary.md").read_text()   # output goes to the PR body, not here
    assert STEPS["Check the author's changes"]["id"] == "check"


def pr_step(runner, configured, code, **extra):
    s = STEPS["Open the fix PR into the reviewed PR's branch"]
    assert s["env"]["CHECK_CODE"] == "${{ steps.check.outputs.code }}"
    assert s["env"]["CHECK_CONFIGURED"] == "${{ inputs.check != '' }}"
    return run_step(s["run"], dict(runner["env"], CHECK_CONFIGURED=configured, CHECK_CODE=code, **extra),
                    runner["work"])


def pulls_call(runner):
    return [c for c in runner["calls"].read_text().splitlines() if c.startswith("api repos/o/r/pulls")]


@pytest.mark.parametrize("configured, code, draft", [
    ("true", "0", "false"), ("true", "1", "true"), ("true", "", "true"), ("false", "", "true")])
def test_fix_pr_is_a_draft_unless_the_check_exited_zero(runner, configured, code, draft):
    (runner["temp"] / "check.txt").write_text("check output\n")
    r = pr_step(runner, configured, code)
    assert r.returncode == 0, r.stderr
    calls = pulls_call(runner)
    assert len(calls) == 1 and f"draft={draft}" in calls[0]
    body = (runner["temp"] / "body.md").read_text()
    sha = git(runner["work"], "rev-parse", "HEAD~1").strip()        # the fix commit (then the log commit)
    assert body.startswith("### Author response") == (draft == "false")
    assert sha[:12] in body or configured == "false"
    comment = [c for c in runner["calls"].read_text().splitlines() if "issues/7/comments" in c]
    assert comment, "the reviewed PR is told"
    assert "| #42 |" in (runner["work"] / "reviews" / "decisions.md").read_text()


def test_the_pr_tree_cannot_replace_the_harness_module(runner):
    """The step holds a GitHub token and its folder is the PR's tree; the harness must come from PYTHONPATH."""
    r = pr_step(runner, "true", "1")
    assert r.returncode == 0, r.stderr
    assert "draft=true" in pulls_call(runner)[0]


def test_a_refused_draft_fails_closed(runner):
    """No normal PR in place of a refused draft (GPT Sol on #9): the run fails and says so; the fixes stay pushed."""
    r = pr_step(runner, "true", "1", GH_NO_DRAFT="1")
    assert r.returncode == 1
    calls = pulls_call(runner)
    assert len(calls) == 1 and "draft=true" in calls[0]                    # one attempt, as a draft only
    err = (runner["temp"] / "respond_error.txt").read_text()
    assert err.startswith("The fix PR was to open as a draft (checks: failed)")
    assert "respond/pr7" in err and "not opened as a normal PR" in err
    assert len(err[:800].splitlines()) >= 3                                 # the explanation fits the comment
    assert not any("issues/7/comments" in c for c in runner["calls"].read_text().splitlines())
    assert "| #42 |" not in (runner["work"] / "reviews" / "decisions.md").read_text()
    remote = git(runner["work"], "ls-remote", "origin", "respond/pr7")
    assert remote.strip(), "the fix branch stays pushed"


def test_a_passing_check_opens_a_normal_pr_in_one_attempt(runner):
    r = pr_step(runner, "true", "0", GH_NO_DRAFT="1")
    assert r.returncode == 0 and len(pulls_call(runner)) == 1 and "draft=false" in pulls_call(runner)[0]


def test_other_pr_failures_do_not_mention_drafts(runner):
    gh = Path(runner["env"]["PATH"].split(":")[0]) / "gh"
    gh.write_text(gh.read_text().replace('if [[ "$*" == *"draft=true"* ]] && [ -n "$GH_NO_DRAFT" ]; then',
                                         'if [ -n "$GH_FAIL" ]; then'))
    r = pr_step(runner, "true", "0", GH_FAIL="1")
    assert r.returncode == 1
    err = (runner["temp"] / "respond_error.txt").read_text()
    assert err.startswith("Opening the fix PR failed") and "was to open as a draft" not in err   # a passing check


# ---- the author's verification -----------------------------------------------------------------------------------------

def answer(fid, decision="accept", method="ran", outcome="passed", detail="pytest -k x", verification=True):
    a = {"finding_id": fid, "decision": decision, "reason": "r", "changes": "a.py"}
    if verification:
        a["verification"] = {"method": method, "outcome": outcome, "detail": detail}
    return a


def resp(answers, passed=True):
    return {"schema_version": 1, "summary": "s", "responses": answers,
            "tests": {"ran": True, "passed": passed, "detail": "25 passed"}}


def env():
    return {"meta": {"model": "gpt-6.1-sol"}, "review": {"verdict": "changes_needed", "summary": "x", "findings": []}}


def test_verification_is_required_and_method_none_cannot_claim_a_result():
    assert RS.response_errors(resp([answer("F1")]), RESP_SCHEMA, ["F1"]) == []
    assert RS.response_errors(resp([answer("F1", verification=False)]), RESP_SCHEMA, ["F1"])     # new answers
    assert RS.response_errors(resp([answer("F1", method="maybe")]), RESP_SCHEMA, ["F1"])
    for outcome in ("passed", "failed"):
        errs = RS.response_errors(resp([answer("F1", method="none", outcome=outcome)]), RESP_SCHEMA, ["F1"])
        assert errs and "method `none`" in errs[0]
    for outcome in ("blocked", "unknown"):
        assert RS.response_errors(resp([answer("F1", method="none", outcome=outcome)]), RESP_SCHEMA, ["F1"]) == []
    assert RS.response_errors(resp([answer("F1", method="read")]), RESP_SCHEMA, ["F1"]) == []   # docs fix


def test_gaps_are_listed_apart_from_the_test_run():
    """notes #23/#24: the configured tests passed while the sketch fixes were only read, their runs blocked."""
    r = resp([answer("F1"),                                                      # ran, passed: no gap
              answer("F2", method="read"),                                       # read, passed: no gap (docs)
              answer("F3", method="read", outcome="blocked", detail="sketch run blocked by a permission prompt"),
              answer("F4", method="ran", outcome="failed"),                      # ran does not mean passed
              answer("F5", method="none", outcome="unknown"),
              answer("F6", decision="reject", method="none", outcome="unknown"),  # changed nothing: no gap
              answer("F7", verification=False)])                                 # a record without the field
    text = RS.render_summary(r, env(), "2026-11-01-pr20-gpt.json", [], [], 20, "claude-opus-5-5")
    assert "**Author's test run: ✅ tests pass**" in text
    gaps = text.split("Verification gaps (4)")[1].split("<details>")[0]
    assert "F3 (accept): read, outcome blocked — sketch run blocked by a permission prompt" in gaps
    assert "F4 (accept): ran, outcome failed" in gaps and "F5 (accept): not checked (unknown)" in gaps
    assert "F7 (accept): verification not reported" in gaps
    assert "F1 " not in gaps and "F2 " not in gaps and "F6 " not in gaps
    assert "| F2 | ✅ accept | 👀 read · ✅ passed |" in text and "| F7 | ✅ accept | ❔ not reported |" in text
    clean = RS.render_summary(resp([answer("F1"), answer("F2", method="read")]), env(), "n.json", [], [], 1, "m")
    assert "no gaps" in clean and "Verification gaps" not in clean
    only_rejects = RS.render_summary(resp([answer("F1", decision="reject", method="read")]), env(), "n", [], [], 1, "m")
    assert "Verification" not in only_rejects.split("<details>")[0]


def test_both_providers_get_the_verification_field():
    strict = CX.strict_schema(RESP_SCHEMA)                               # Codex: OpenAI strict structured outputs
    item = strict["properties"]["responses"]["items"]
    assert "verification" in item["required"]
    v = item["properties"]["verification"]
    assert v["required"] == ["method", "outcome", "detail"] and v["additionalProperties"] is False
    assert v["properties"]["outcome"]["enum"] == ["passed", "failed", "blocked", "unknown"]
    from review_harness.providers import claude_code as CC
    assert "verification" in CC.cli_schema(RESP_SCHEMA)["properties"]["responses"]["items"]["required"]


@pytest.mark.parametrize("path", ["templates/review/RESPOND.md", "tests/fixture/review/RESPOND.md"])
def test_respond_instructions_explain_verification(path):
    text = (REPO / path).read_text()
    for word in ("`ran`", "`read`", "`none`", "`blocked`", "`unknown`"):
        assert word in text, (path, word)
