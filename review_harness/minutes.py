"""Report a repo's GitHub Actions use per workflow and job, keeping measured, estimated and unknown numbers apart.

Example:
  GITHUB_TOKEN=... python -m review_harness.minutes --repo owner/name --since 2026-10-01 [--until 2026-10-31]

Every run created in the window is read, with every attempt of every job (`filter=all`) across all pages; a job is
counted once by its ID. For each job:

  measured   seconds from `started_at` to `completed_at`
  estimated  the measured time rounded up to a whole minute, as GitHub bills each hosted-runner job
  unknown    a job that ran but lacks a timestamp (still running, or GitHub did not record it): counted, not guessed

Skipped jobs never get a runner and count as zero. Runner multipliers (Windows, macOS) and larger runners are not
applied: jobs whose labels are not a standard Linux runner are listed so they can be checked by hand. Model provider
costs (subscriptions, API credits) are not Actions minutes and are not covered here. The account's allowance is shown
only when the billing API returns it (`--allowance-user`).
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from datetime import datetime

API = "https://api.github.com"
LINUX = ("ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04", "ubuntu-20.04", "ubuntu-slim")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def paged(get_json, path: str, key: str, params: dict | None = None) -> tuple[list[dict], int | None]:
    """(all items under `key` across pages of 100, the API's total_count), stopping at a short page."""
    items, page, total = [], 1, None
    while True:
        data = get_json(path, dict(params or {}, per_page=100, page=page))
        batch = data.get(key) or []
        items += batch
        total = data.get("total_count", total)
        if len(batch) < 100 or (total is not None and len(items) >= total):
            return items, total
        page += 1


def job_usage(job: dict) -> dict:
    """{"status": "measured" | "skipped" | "unknown", "seconds": float | None, "minutes": int | None}."""
    if job.get("conclusion") == "skipped":
        return {"status": "skipped", "seconds": 0.0, "minutes": 0}
    start, end = parse_time(job.get("started_at")), parse_time(job.get("completed_at"))
    if job.get("status") != "completed" or start is None or end is None or end < start:
        return {"status": "unknown", "seconds": None, "minutes": None}
    seconds = (end - start).total_seconds()
    return {"status": "measured", "seconds": seconds, "minutes": math.ceil(seconds / 60) if seconds > 0 else 0}


def collect(get_json, repo: str, since: str, until: str | None = None) -> dict:
    """Read the runs created in [since, until] and every job attempt in them."""
    created = f"{since}..{until}" if until else f">={since}"
    runs, total = paged(get_json, f"/repos/{repo}/actions/runs", "workflow_runs", {"created": created})
    seen_runs, jobs = set(), {}
    for run in runs:
        if run["id"] in seen_runs:
            continue
        seen_runs.add(run["id"])
        run_jobs, _ = paged(get_json, f"/repos/{repo}/actions/runs/{run['id']}/jobs", "jobs", {"filter": "all"})
        for job in run_jobs:
            jobs.setdefault(job["id"], dict(job, workflow=run.get("name") or run.get("path") or "?",
                                            event=run.get("event", "?")))
    # A filtered run list stops at 1,000 results; say so rather than report a silently partial total.
    missing = (total - len(runs)) if total is not None and total > len(runs) else 0
    return {"runs": len(seen_runs), "jobs": list(jobs.values()), "runs_not_read": missing}


def summarise(jobs: list[dict]) -> dict:
    """Totals per workflow, per (workflow, job name) and overall."""
    def blank():
        return {"jobs": 0, "attempts_after_first": 0, "seconds": 0.0, "minutes": 0, "unknown": 0, "skipped": 0,
                "failed_or_cancelled": 0}
    per_wf, per_job, total = defaultdict(blank), defaultdict(blank), blank()
    other_runners = set()
    for job in jobs:
        u = job_usage(job)
        name = job.get("name", "?")
        for bucket in (per_wf[job["workflow"]], per_job[(job["workflow"], name)], total):
            bucket["jobs"] += 1
            bucket["attempts_after_first"] += 1 if (job.get("run_attempt") or 1) > 1 else 0
            bucket["failed_or_cancelled"] += 1 if job.get("conclusion") in ("failure", "cancelled", "timed_out") else 0
            if u["status"] == "unknown":
                bucket["unknown"] += 1
            elif u["status"] == "skipped":
                bucket["skipped"] += 1
            else:
                bucket["seconds"] += u["seconds"]
                bucket["minutes"] += u["minutes"]
        labels = job.get("labels") or []
        if u["status"] == "measured" and labels and not any(lbl in LINUX for lbl in labels):
            other_runners.add(", ".join(labels))
    return {"workflows": dict(per_wf), "jobs": dict(per_job), "total": total, "other_runners": sorted(other_runners)}


def allowance(get_json, user: str) -> dict | None:
    """The account's Actions minutes from the billing API, or None when it does not answer."""
    try:
        data = get_json(f"/users/{user}/settings/billing/actions", {})
    except Exception:  # noqa: BLE001 - the endpoint needs billing access and may be retired; report unavailable
        return None
    if not isinstance(data, dict) or "included_minutes" not in data:
        return None
    return {k: data.get(k) for k in ("total_minutes_used", "included_minutes", "total_paid_minutes_used")}


def render(repo: str, since: str, until: str | None, runs: int, s: dict, allow: dict | None,
           allow_user: str | None, runs_not_read: int = 0) -> str:
    def mins(seconds):
        return f"{seconds / 60:.1f}"
    t = s["total"]
    lines = [f"## Actions use in {repo}, runs created {since} to {until or 'now'}", "",
             f"{runs} runs, {t['jobs']} jobs (every attempt; {t['attempts_after_first']} from re-runs; "
             f"{t['failed_or_cancelled']} failed, cancelled or timed out; {t['skipped']} skipped).", "",
             "| Workflow | Jobs | Measured min | Estimated billed min | Jobs without timestamps |",
             "|---|---|---|---|---|"]
    for wf, b in sorted(s["workflows"].items(), key=lambda kv: -kv[1]["minutes"]):
        lines.append(f"| {wf} | {b['jobs']} | {mins(b['seconds'])} | {b['minutes']} | {b['unknown']} |")
    lines.append(f"| **Total** | {t['jobs']} | {mins(t['seconds'])} | {t['minutes']} | {t['unknown']} |")
    lines += ["", "<details><summary>Per job</summary>", "",
              "| Workflow | Job | Jobs | Measured min | Estimated billed min | Without timestamps |",
              "|---|---|---|---|---|---|"]
    for (wf, name), b in sorted(s["jobs"].items(), key=lambda kv: -kv[1]["minutes"]):
        lines.append(f"| {wf} | {name} | {b['jobs']} | {mins(b['seconds'])} | {b['minutes']} | {b['unknown']} |")
    lines += ["", "</details>", "",
              "- *Measured*: job start to end. *Estimated billed*: each job rounded up to a whole minute, as GitHub "
              "bills hosted runners; not an invoice.",
              "- Jobs without timestamps are counted, not estimated."]
    if runs_not_read:
        lines.append(f"- **Incomplete**: the API listed {runs_not_read} more runs than it returned (filtered lists stop "
                     "at 1,000); use a shorter window.")
    if s["other_runners"]:
        lines.append("- Not a standard Linux runner (multipliers not applied; check by hand): "
                     + "; ".join(s["other_runners"]))
    lines.append("- Not covered: model provider costs (subscriptions, API credits).")
    if allow_user:
        if allow:
            lines.append(f"- Account `{allow_user}` (billing API): {allow['total_minutes_used']} of "
                         f"{allow['included_minutes']} included minutes used this cycle; "
                         f"{allow['total_paid_minutes_used']} paid.")
        else:
            lines.append(f"- Account `{allow_user}` allowance: unavailable (the billing API did not return it).")
    return "\n".join(lines) + "\n"


def github_getter(token: str):
    import requests
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28"})

    def get_json(path: str, params: dict):
        r = session.get(API + path, params=params, timeout=60)
        r.raise_for_status()
        return r.json()
    return get_json


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--since", required=True, help="first day, YYYY-MM-DD (runs created on or after it)")
    ap.add_argument("--until", help="last day, YYYY-MM-DD (default: now)")
    ap.add_argument("--allowance-user", help="account login whose included minutes to show, if the API allows")
    args = ap.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("Set GITHUB_TOKEN or GH_TOKEN (read access to Actions).", file=sys.stderr)
        return 2
    get_json = github_getter(token)
    data = collect(get_json, args.repo, args.since, args.until)
    allow = allowance(get_json, args.allowance_user) if args.allowance_user else None
    sys.stdout.write(render(args.repo, args.since, args.until, data["runs"], summarise(data["jobs"]), allow,
                            args.allowance_user, data["runs_not_read"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
