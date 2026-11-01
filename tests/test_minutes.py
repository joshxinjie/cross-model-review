"""Actions minutes report (plan v3 A3): every attempt and page, each job once, measured vs estimated vs unknown."""

from review_harness import minutes as M

T0 = "2026-10-30T01:00:00Z"


def job(jid, name="review", attempt=1, start=T0, end="2026-10-30T01:02:10Z", conclusion="success",
        status="completed", labels=("ubuntu-latest",)):
    return {"id": jid, "name": name, "run_attempt": attempt, "started_at": start, "completed_at": end,
            "conclusion": conclusion, "status": status, "labels": list(labels)}


def fake_api(runs, jobs_by_run, runs_total=None, page_size=100):
    """A get_json that pages like GitHub and records every request."""
    calls = []

    def get_json(path, params):
        calls.append((path, dict(params)))
        page, per = params["page"], params["per_page"]
        if path.endswith("/actions/runs"):
            items, key, total = runs, "workflow_runs", runs_total if runs_total is not None else len(runs)
        else:
            assert params.get("filter") == "all", "jobs must be read for every attempt"
            run_id = int(path.split("/")[-2])
            items, key, total = jobs_by_run[run_id], "jobs", len(jobs_by_run[run_id])
        return {"total_count": total, key: items[(page - 1) * per: page * per]}
    return get_json, calls


def test_reruns_failed_cancelled_skipped_and_missing_timestamps():
    runs = [{"id": 1, "name": "Cross-model review", "event": "issue_comment"},
            {"id": 2, "name": "Tests", "event": "pull_request"}]
    jobs = {1: [job(11, "review / gate", end="2026-10-30T01:00:12Z"),                    # 12 s -> 1 billed min
                job(12, "review / review", conclusion="failure"),                        # first attempt failed
                job(13, "review / review", attempt=2),                                   # re-run: counted too
                job(14, "review / review", attempt=2, end=None, status="in_progress"),   # no end time
                job(15, "respond / respond", conclusion="skipped", start=None, end=None)],
            2: [job(21, "test", conclusion="cancelled", end="2026-10-30T01:00:00Z")]}    # 0 s
    get_json, calls = fake_api(runs, jobs)
    data = M.collect(get_json, "o/r", "2026-10-01", "2026-10-31")
    assert ("/repos/o/r/actions/runs", {"created": "2026-10-01..2026-10-31", "per_page": 100, "page": 1}) in calls
    s = M.summarise(data["jobs"])
    t = s["total"]
    assert data["runs"] == 2 and t["jobs"] == 6
    assert t["attempts_after_first"] == 2 and t["failed_or_cancelled"] == 2 and t["skipped"] == 1
    assert t["unknown"] == 1                                   # counted, not guessed
    assert t["minutes"] == 1 + 3 + 3 + 0 and round(t["seconds"]) == 12 + 130 + 130
    review = s["workflows"]["Cross-model review"]
    assert review["minutes"] == 7 and review["unknown"] == 1
    text = M.render("o/r", "2026-10-01", "2026-10-31", data["runs"], s, None, None)
    assert "| **Total** | 6 | 4.5 | 7 | 1 |" in text
    assert "counted, not estimated" in text and "Not covered: model provider costs" in text
    assert "allowance" not in text                              # not asked for


def test_every_page_is_read_and_each_job_counted_once():
    runs = [{"id": i, "name": "Tests"} for i in range(1, 251)]
    runs.insert(100, runs[99])                                 # a run that shifted onto the next page
    jobs = {i: [job(1000 + i)] for i in range(1, 251)}
    jobs[7] = [job(5000 + k, attempt=1 + k // 120) for k in range(230)]   # 230 attempts: three pages of jobs
    get_json, calls = fake_api(runs, jobs, runs_total=251)
    data = M.collect(get_json, "o/r", "2026-10-01")
    assert data["runs"] == 250 and len(data["jobs"]) == 249 + 230
    assert data["runs_not_read"] == 0
    assert sum(1 for p, q in calls if p.endswith("/runs/7/jobs")) == 3
    assert ("/repos/o/r/actions/runs", {"created": ">=2026-10-01", "per_page": 100, "page": 3}) in calls


def test_a_list_cut_short_by_the_api_is_reported_as_incomplete():
    runs = [{"id": i, "name": "Tests"} for i in range(1, 4)]
    get_json, _ = fake_api(runs, {i: [] for i in range(1, 4)}, runs_total=1200)
    data = M.collect(get_json, "o/r", "2026-10-01")
    assert data["runs_not_read"] == 1197
    text = M.render("o/r", "2026-10-01", None, data["runs"], M.summarise(data["jobs"]), None, None,
                    data["runs_not_read"])
    assert "**Incomplete**" in text


def test_job_times_are_rounded_up_per_job_and_bad_times_are_unknown():
    assert M.job_usage(job(1, end="2026-10-30T01:01:00Z")) == {"status": "measured", "seconds": 60.0, "minutes": 1}
    assert M.job_usage(job(1, end="2026-10-30T01:01:01Z"))["minutes"] == 2
    assert M.job_usage(job(1, start=None))["status"] == "unknown"
    assert M.job_usage(job(1, end="2026-10-30T00:59:00Z"))["status"] == "unknown"    # ends before it starts
    assert M.job_usage(job(1, status="queued", start=None, end=None))["status"] == "unknown"


def test_other_runners_are_flagged_not_multiplied():
    s = M.summarise([dict(job(1, labels=("macos-14",)), workflow="Build"), dict(job(2), workflow="Build")])
    assert s["other_runners"] == ["macos-14"] and s["total"]["minutes"] == 6
    assert "multipliers not applied" in M.render("o/r", "d", None, 1, s, None, None)


def test_allowance_only_when_the_billing_api_answers():
    def broken(path, params):
        raise RuntimeError("410 Gone")
    assert M.allowance(broken, "me") is None
    assert M.allowance(lambda p, q: {"message": "Not Found"}, "me") is None
    ok = M.allowance(lambda p, q: {"total_minutes_used": 812, "included_minutes": 2000,
                                   "total_paid_minutes_used": 0}, "me")
    s = M.summarise([])
    assert "812 of 2000 included minutes" in M.render("o/r", "d", None, 0, s, ok, "me")
    assert "allowance: unavailable" in M.render("o/r", "d", None, 0, s, None, "me")
