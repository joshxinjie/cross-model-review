"""Which review of a pull request this is, and whether it is a closing review (plan v3 C2).

A project opts in with `limits.full_reviews: N` in review/config.yaml (its REVIEW.md describes the rule). The first N
reviews of a PR are full reviews; from review N+1 on, a review is a closing review: it checks the fixes made since the
earlier reviews, what they touch and regressions, and in code those fixes did not change it reports only new
`critical` and `major` findings and questions needed to establish correctness or a serious risk. Without the
setting, nothing changes.

Counting reads the review archive (reviewer/archive), not file names: every valid, completed review of this PR across
dates and reviewers counts, including `/review force` repeats; author responses, project reviews and invalid
envelopes (which run.py still writes) do not, and failed runs leave no file. If the history cannot be read, the
review is a full one: missing history never narrows a review. `/review full` asks for a full review whatever the
count; it widens the scope only, and the reviewer still sees the decision log, so it is not a blind review.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

PR_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}-pr(\d+)-.+\.json$")


def full_reviews(cfg: dict) -> int | None:
    """The project's `limits.full_reviews`, or None when it has not opted in."""
    value = (cfg.get("limits") or {}).get("full_reviews")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def prior_reviews(names_newest_first: list[str] | None, pr: int, read) -> list[dict] | None:
    """Valid completed reviews of PR #pr, newest first, as {"name", "commit"}; None if any record can't be read."""
    if names_newest_first is None:
        return None
    seen, out = set(), []
    for path in names_newest_first:
        name = Path(path).name
        m = PR_FILE.match(name)
        if not m or int(m.group(1)) != pr or "-response" in name or name in seen:
            continue
        seen.add(name)
        try:
            env = read(name)
        except Exception:  # noqa: BLE001 - an unreadable record means the count is unknown
            return None
        if not isinstance(env, dict):
            return None
        meta = env.get("meta") or {}
        if "invalid" in meta or not env.get("review") or (env.get("review") or {}).get("scope", "pr") != "pr":
            continue
        out.append({"name": name, "commit": meta.get("commit") or ""})
    return out


def review_round(cfg: dict, pr: int | None, prior: list[dict] | None, full_requested: bool = False) -> dict:
    """{"number": n or None, "closing": bool, "full_reviews": N or None, "since": commit of the newest review}."""
    limit = full_reviews(cfg)
    if pr is None or prior is None:
        return {"number": None, "closing": False, "full_reviews": limit, "since": ""}
    number = len(prior) + 1
    closing = bool(limit) and number > limit and not full_requested
    return {"number": number, "closing": closing, "full_reviews": limit,
            "since": prior[0]["commit"] if prior else ""}


def closing_task(info: dict, pr: int) -> str:
    """The extra instructions a closing review gets, ahead of the material."""
    since = (f" The newest earlier review read commit `{info['since']}`: `git diff {info['since']}..HEAD` shows what "
             "changed since." if info.get("since") else "")
    return (f"This is review {info['number']} of PR #{pr}. This project gives a PR {info['full_reviews']} full "
            f"reviews; from then on a review is a *closing review* (REVIEW.md).{since}\n"
            "In a closing review:\n"
            "- Check the fixes made since the earlier reviews (their findings and decisions are in "
            "`reviews/decisions.md`), the code those fixes touch, and regressions they cause. Report any problem "
            "there at the severity it deserves.\n"
            "- Check every finding from earlier reviews that is still unresolved.\n"
            "- In code the fixes did not change, report only new `critical` and `major` findings, and a `question` "
            "only when it is needed to establish correctness or a serious risk. Leave out `minor`, `nit` and "
            "cosmetic suggestions there.\n"
            "- Severities and the verdict rules are unchanged. Open findings go to the owner to decide; they are not "
            "sent for another automatic round.\n")


def archive_history(root: Path) -> list[str] | None:
    """Review file names on origin/reviewer/archive, newest first; [] if there is no archive yet; None if it exists
    but can't be listed."""
    exists = subprocess.run(["git", "-C", str(root), "rev-parse", "-q", "--verify", "origin/reviewer/archive"],
                            capture_output=True, text=True)
    if exists.returncode != 0:
        return []
    out = subprocess.run(["git", "-C", str(root), "log", "--format=", "--name-only", "--diff-filter=A",
                          "origin/reviewer/archive", "--", "reviews/"], capture_output=True, text=True)
    return [line for line in out.stdout.splitlines() if line.strip()] if out.returncode == 0 else None


def read_record(root: Path, name: str):
    out = subprocess.run(["git", "-C", str(root), "show", f"origin/reviewer/archive:reviews/{name}"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise OSError(f"cannot read reviews/{name} from reviewer/archive")
    return json.loads(out.stdout)


def round_for(root: Path, cfg: dict, pr: int | None, full_requested: bool = False) -> dict:
    """The round of a PR review in this checkout. Only reads the archive when the project has opted in."""
    if pr is None or full_reviews(cfg) is None:
        return {"number": None, "closing": False, "full_reviews": full_reviews(cfg), "since": ""}
    prior = prior_reviews(archive_history(root), pr, lambda name: read_record(root, name))
    return review_round(cfg, pr, prior, full_requested)
