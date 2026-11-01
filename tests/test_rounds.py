"""Closing reviews (plan v3 C2): counting a PR's reviews from the archive, the closing-review instructions, the posted
summary, `/review full`, and opt-in through limits.full_reviews."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from review_harness import gate as G
from review_harness import post as P
from review_harness import prompt as PR
from review_harness import rounds as R

REPO = Path(__file__).resolve().parents[1]
ON = {"limits": {"full_reviews": 2}}


def env(pr=20, commit="c", invalid=False, scope="pr"):
    e = {"meta": {"pr": pr, "commit": commit}, "review": {"scope": scope, "verdict": "approve", "findings": []}}
    if invalid:
        e["meta"]["invalid"] = ["bad"]
        e["review"] = None
    return e


ARCHIVE = {   # newest first, as `git log --diff-filter=A` lists them
    "reviews/2026-11-01-pr20-gpt-5.json": env(commit="c6"),
    "reviews/2026-11-01-pr20-gpt-4-response.json": {"response": {}},
    "reviews/2026-11-01-pr20-gpt-4.json": env(commit="c5", invalid=True),     # written, but failed validation
    "reviews/2026-11-01-pr20-fable.json": env(commit="c4"),                   # another reviewer, same PR
    "reviews/2026-11-01-pr2-gpt.json": env(pr=2, commit="x"),                 # pr2 is not pr20
    "reviews/2026-11-01-project-gpt.json": env(scope="project"),
    "reviews/2026-11-01-pr20-gpt.json": env(commit="c3"),
    "reviews/2026-10-31-pr20-gpt.json": env(commit="c1"),                     # an earlier day
}


def read(name):
    return ARCHIVE["reviews/" + name]


@pytest.mark.parametrize("value, expect", [(2, 2), (1, 1), (None, None), (0, None), (-1, None), ("2", None),
                                           (True, None), (2.5, None)])
def test_full_reviews_is_opt_in(value, expect):
    cfg = {"limits": {} if value is None else {"full_reviews": value}}
    assert R.full_reviews(cfg) == expect
    assert R.full_reviews({}) is None


def test_reviews_are_counted_from_contents_across_dates_and_reviewers():
    prior = R.prior_reviews(list(ARCHIVE), 20, read)
    assert [p["name"] for p in prior] == ["2026-11-01-pr20-gpt-5.json", "2026-11-01-pr20-fable.json",
                                          "2026-11-01-pr20-gpt.json", "2026-10-31-pr20-gpt.json"]
    assert [(p["name"], p["commit"]) for p in R.prior_reviews(list(ARCHIVE), 2, read)] == [
        ("2026-11-01-pr2-gpt.json", "x")]
    assert R.prior_reviews(list(ARCHIVE) + ["reviews/2026-10-31-pr20-gpt.json"], 20, read)[-1]["commit"] == "c1"
    assert R.prior_reviews([], 20, read) == []


def test_unreadable_history_means_unknown_never_fewer():
    assert R.prior_reviews(None, 20, read) is None

    def broken(name):
        if name == "2026-11-01-pr20-fable.json":
            raise OSError("gone")
        return read(name)
    assert R.prior_reviews(list(ARCHIVE), 20, broken) is None
    assert R.prior_reviews(list(ARCHIVE), 20, lambda n: None if "fable" in n else read(n)) is None


def test_review_three_on_is_a_closing_review_only_when_opted_in():
    two = [{"name": "b", "commit": "c2", "findings": []}, {"name": "a", "commit": "c1", "findings": []}]
    assert R.review_round(ON, 20, [])["closing"] is False                             # review 1
    assert R.review_round(ON, 20, two[1:])["closing"] is False                        # review 2
    third = R.review_round(ON, 20, two)
    assert {k: third[k] for k in ("number", "closing", "full_reviews", "since")} == {
        "number": 3, "closing": True, "full_reviews": 2, "since": "c2"}
    assert [h["name"] for h in third["history"]] == ["a", "b"]                       # oldest first
    assert R.review_round(ON, 20, two, full_requested=True)["closing"] is False      # /review full
    assert R.review_round({"limits": {}}, 20, two * 5)["closing"] is False           # not opted in
    unknown = R.review_round(ON, 20, None)
    assert unknown["closing"] is False and unknown["number"] is None                 # history unknown: full
    assert R.review_round(ON, None, two)["closing"] is False


def git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout


def test_end_to_end_on_a_real_archive_branch(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    assert R.archive_history(repo) == []                                              # no archive yet
    assert R.round_for(repo, ON, 20)["number"] == 1
    git(repo, "checkout", "-q", "--orphan", "reviewer/archive")
    (repo / "reviews").mkdir()
    for i, (name, e) in enumerate(reversed(list(ARCHIVE.items()))):                  # oldest added first
        (repo / name).write_text(json.dumps(e))
        git(repo, "add", name)
        git(repo, "commit", "-q", "-m", f"add {i}")
    git(repo, "update-ref", "refs/remotes/origin/reviewer/archive", "HEAD")
    info = R.round_for(repo, ON, 20)
    assert (info["number"], info["closing"], info["since"]) == (5, True, "c6") and len(info["history"]) == 4
    assert R.round_for(repo, ON, 20, full_requested=True)["closing"] is False
    assert R.round_for(repo, {"limits": {}}, 20)["number"] is None                   # not opted in: not even read
    (repo / "reviews" / "2026-11-02-pr20-gpt.json").write_text("{not json")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "broken")
    git(repo, "update-ref", "refs/remotes/origin/reviewer/archive", "HEAD")
    assert R.round_for(repo, ON, 20) == {"number": None, "closing": False, "full_reviews": 2, "since": "",
                                         "history": []}


def pack(round_info=None):
    return {"scope": "pr", "files": [], "dropped": [], "text": "DIFF", "tokens": 1, "pr": 20,
            **({"round": round_info} if round_info is not None else {})}


def test_closing_instructions_reach_the_reviewer_only_in_a_closing_review():
    root = REPO / "tests" / "fixture"
    from review_harness.config import load_config
    cfg = load_config(root)
    _, plain = PR.build_prompt(root, cfg, pack())
    _, full = PR.build_prompt(root, cfg, pack({"number": 2, "closing": False, "full_reviews": 2, "since": "c1"}))
    assert plain == full and "closing review" not in plain                          # full reviews: prompt unchanged
    _, closing = PR.build_prompt(root, cfg, pack({"number": 3, "closing": True, "full_reviews": 2, "since": "abc1234"}))
    assert "This is review 3 of PR #20" in closing and "`git diff abc1234..HEAD`" in closing
    assert "only new `critical` and `major` findings" in closing and "Leave out `minor`, `nit`" in closing
    assert "Check every earlier finding above" in closing
    assert closing.index("closing review") < closing.index("DIFF")
    _, nosince = PR.build_prompt(root, cfg, pack({"number": 3, "closing": True, "full_reviews": 2, "since": ""}))
    assert "git diff" not in nosince


def summary(meta):
    e = {"meta": {"reviewer": "gpt", "model": "m", "input_tokens": 1, "output_tokens": 1, **meta},
         "review": {"verdict": "changes_needed", "summary": "s", "findings": []}}
    return P.render_summary(e, [])


def test_the_posted_summary_says_who_decides_after_a_closing_review():
    closing = summary({"review_number": 3, "closing_review": True})
    assert "**Closing review**" in closing and "owner's to decide" in closing and "review 3 of this PR" in closing
    assert "Comment `/respond` for the author's answer" not in closing
    normal = summary({"review_number": 2, "closing_review": False})
    assert "Comment `/respond` for the author's answer" in normal and "Closing review" not in normal
    assert "review 4 of this PR (full review requested)" in summary({"review_number": 4, "full_requested": True})
    assert "of this PR" not in summary({})                                          # not opted in: as before


@pytest.mark.parametrize("body, ok, name, full, force", [
    ("/review full", True, None, True, False),
    ("/review fable full", True, "fable", True, False),
    ("/review full force", True, None, True, True),
    ("/review force full", True, None, True, True),
    ("/review gpt force", True, "gpt", False, True),
    ("/review", True, None, False, False),
    ("/review full fable", False, None, False, False),          # the reviewer's name comes first
    ("/review fully", True, "fully", False, False),
    ("/review fable please", False, None, False, False),
])
def test_review_full_command(body, ok, name, full, force):
    assert G.parse_command(body) == (ok, name)
    assert G.wants_full(body) is full and G.wants_force(body) is force


def test_the_gate_passes_full_through_to_the_review_step():
    from test_review_harness import CFG, TODAY, comment_event, pr_json
    out = G.resolve("issue_comment", comment_event("/review full"), {}, CFG, lambda p: pr_json(), [], TODAY)
    assert out["run"] == "true" and out["full"] == "true"
    assert G.resolve("issue_comment", comment_event("/review"), {}, CFG, lambda p: pr_json(), [], TODAY)["full"] == "false"
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "review.yml").read_text())
    assert wf["jobs"]["gate"]["outputs"]["full"] == "${{ steps.gate.outputs.full }}"
    step = [s for s in wf["jobs"]["review"]["steps"] if s.get("name") == "Run the review"][0]
    assert step["env"]["FULL"] == "${{ needs.gate.outputs.full }}"
    assert 'if [ "$FULL" = true ]; then full_flag="--full"; fi' in step["run"] and "$full_flag" in step["run"]


class SeeingReviewer:
    """Fake reviewer that keeps the prompt it was given and approves."""
    model = "fake-reviewer"

    def __init__(self):
        self.user = None

    def complete(self, system, messages, max_output_tokens):
        from review_harness.providers.base import Completion
        self.user = messages[0]["content"]
        return Completion(json.dumps({"schema_version": 1, "scope": "pr", "verdict": "approve", "summary": "ok",
                                      "findings": []}), 1, 1)


@pytest.mark.parametrize("limits, full, number, closing", [
    ({"full_reviews": 2}, False, 3, True), ({"full_reviews": 2}, True, 3, False),
    ({"full_reviews": 5}, False, 3, False), ({}, False, None, None)])
def test_run_tells_the_reviewer_and_records_the_round(tmp_path, monkeypatch, limits, full, number, closing):
    from review_harness import run as RN
    from review_harness.config import load_config
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "head")
    head = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-q", "--orphan", "reviewer/archive")
    git(repo, "rm", "-rqf", ".")
    (repo / "reviews").mkdir()
    for name, commit in (("2026-10-31-pr20-gpt.json", "c1"), ("2026-11-01-pr20-gpt.json", "c2")):
        (repo / "reviews" / name).write_text(json.dumps(env(commit=commit)))
        git(repo, "add", f"reviews/{name}")
        git(repo, "commit", "-q", "-m", name)
    git(repo, "update-ref", "refs/remotes/origin/reviewer/archive", "HEAD")
    git(repo, "checkout", "-q", "main")
    cfg = load_config(REPO / "tests" / "fixture")
    cfg["limits"] = {**cfg["limits"], **limits}
    if not limits:
        cfg["limits"].pop("full_reviews", None)
    reviewer = SeeingReviewer()
    monkeypatch.setattr(RN, "load_config", lambda root: cfg)
    monkeypatch.setattr(RN, "get_provider", lambda r, work_dir=None: reviewer)
    monkeypatch.setattr(RN, "build_pr_pack", lambda *a, **k: {"scope": "pr", "files": [], "dropped": [],
                                                              "text": "DIFF", "tokens": 1})
    out = tmp_path / "out.json"
    argv = ["--scope", "pr", "--pr", "20", "--repo-dir", str(repo), "--head", "HEAD", "--out", str(out)]
    assert RN.main(argv + (["--full"] if full else [])) == 0
    meta = json.loads(out.read_text())["meta"]
    assert meta["commit"] == head
    assert meta.get("review_number") == number and meta.get("closing_review", None) is closing
    assert ("This is review 3 of PR #20" in reviewer.user) is bool(closing)
    if closing:
        assert "`git diff c2..HEAD`" in reviewer.user
    assert meta.get("full_requested", False) is (full and bool(limits))


# ---- GPT Sol's review of #10 ------------------------------------------------------------------------------------------

def finding(fid, sev="major", title="t", file="a.py", line=3):
    return {"id": fid, "severity": sev, "title": title, "file": file, "line_start": line}


def env_with(findings, commit, reviewer="gpt"):
    return {"meta": {"pr": 20, "commit": commit, "reviewer": reviewer},
            "review": {"scope": "pr", "verdict": "changes_needed", "findings": findings}}


def test_a_closing_review_gets_every_earlier_finding_even_unanswered_ones():
    """Two valid earlier reviews nobody answered: no decision rows anywhere. Both lists must reach the reviewer."""
    names = ["reviews/2026-11-01-pr20-gpt.json", "reviews/2026-10-31-pr20-gpt.json"]
    records = {"2026-10-31-pr20-gpt.json": env_with([finding("F1", title="crash on resume"),
                                                     finding("F2", "minor", "typo", "b.md", 9)], "c1"),
               "2026-11-01-pr20-gpt.json": env_with([finding("F1", "critical", "stop reason ignored")], "c2")}
    prior = R.prior_reviews(names, 20, lambda n: records[n])
    info = R.review_round(ON, 20, prior, log_texts=[])
    assert info["closing"] is True
    task = R.closing_task(info, 20)
    assert task.index("2026-10-31-pr20-gpt.json") < task.index("2026-11-01-pr20-gpt.json")      # oldest first
    assert "F1 `major` crash on resume (a.py:3) — recorded: not answered" in task
    assert "F2 `minor` typo (b.md:9) — recorded: not answered" in task
    assert "F1 `critical` stop reason ignored (a.py:3) — recorded: not answered" in task
    assert "not proof that it holds" in task


def test_dispositions_come_from_the_pr_branch_log_and_main():
    log_main = ("| ID | Date | Review | Finding | Reviewer | Severity | Decision | Reason | Fixed in |\n|---|\n"
                "| PR20-F1 | 2026-10-31 | [2026-10-31-pr20-gpt.json](x) | F1: crash | gpt | major | defer | later | — |\n")
    log_branch = log_main + ("| PR20-F2 | 2026-10-31 | [2026-10-31-pr20-gpt.json](x) | F2: typo | gpt | minor | "
                             "accept | ok | #21 |\n"
                             "| PR20-F1b | 2026-11-01 | [2026-10-31-pr20-gpt.json](x) | F1: crash | gpt | major | "
                             "reject | wrong | — |\n"
                             "| PR20-2-F1 | 2026-11-01 | [2026-11-01-pr20-gpt.json](y) | F1: other | gpt | major | "
                             "accept | ok | #22 |\n")
    d = R.dispositions([log_main, log_branch], "2026-10-31-pr20-gpt.json")
    assert d == {"F1": "reject", "F2": "accept (fixed in #21)"}                     # the later row wins
    assert R.dispositions([log_branch], "2026-10-31-pr20-gpt-2.json") == {}          # no prefix collisions


def test_history_too_long_to_list_falls_back_to_a_full_review():
    big = [{"name": f"r{i}", "commit": f"c{i}", "findings": [finding(f"F{k}") for k in range(1, 16)]}
           for i in range(7)]                                                        # 105 findings
    info = R.review_round(ON, 20, big)
    assert info["number"] == 8 and info["closing"] is False and info["history"] == []


def test_a_review_whose_findings_cannot_be_listed_means_unknown():
    bad = {"meta": {"pr": 20, "commit": "c"}, "review": {"scope": "pr", "verdict": "approve", "findings": "oops"}}
    assert R.prior_reviews(["reviews/2026-11-01-pr20-gpt.json"], 20, lambda n: bad) is None


def test_round_for_reads_the_pr_branch_decision_log(tmp_path):
    repo, main = tmp_path / "r", tmp_path / "main"
    repo.mkdir()
    (main / "reviews").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    git(repo, "checkout", "-q", "--orphan", "reviewer/archive")
    (repo / "reviews").mkdir()
    for name, commit in (("2026-10-31-pr20-gpt.json", "c1"), ("2026-11-01-pr20-gpt.json", "c2")):
        (repo / "reviews" / name).write_text(json.dumps(env_with([finding("F1")], commit)))
        git(repo, "add", f"reviews/{name}")
        git(repo, "commit", "-q", "-m", name)
    git(repo, "update-ref", "refs/remotes/origin/reviewer/archive", "HEAD")
    (repo / "reviews" / "decisions.md").write_text(
        "| PR20-F1 | d | [2026-10-31-pr20-gpt.json](x) | F1: t | gpt | major | accept | ok | #21 |\n")
    (main / "reviews" / "decisions.md").write_text("")                              # not merged into main yet
    info = R.round_for(repo, ON, 20, trusted=main)
    assert info["closing"] is True
    recorded = [f["disposition"] for h in info["history"] for f in h["findings"]]
    assert recorded == ["accept (fixed in #21)", "not answered"]
