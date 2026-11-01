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
        findings = env["review"].get("findings")
        if not isinstance(findings, list):
            return None                                  # a review we can't list can't be checked: unknown
        out.append({"name": name, "commit": meta.get("commit") or "",
                    "reviewer": meta.get("reviewer") or "", "findings": findings})
    return out


MAX_LISTED_FINDINGS = 90       # six full reviews of 15; more history than this falls back to a full review


def dispositions(log_texts: list[str], review_name: str) -> dict[str, str]:
    """{"F1": "accept (fixed in #21)", ...} from decision-log rows that name this review file. Several logs may be
    given (the PR branch's, where fix-PR rows land, and main's); a later row for the same finding wins."""
    from .respond import mentions, table_rows
    out = {}
    for text in log_texts:
        for cells in table_rows(text or ""):
            if len(cells) < 7 or not mentions(cells[2], review_name):
                continue
            fid = cells[3].split(":", 1)[0].strip()
            if not re.fullmatch(r"F\d{1,2}", fid):
                continue
            decision = cells[6].strip() or "?"
            fixed = cells[8].strip() if len(cells) > 8 else ""
            out[fid] = decision + (f" (fixed in {fixed})" if fixed and fixed not in ("—", "-") else "")
    return out


def review_round(cfg: dict, pr: int | None, prior: list[dict] | None, full_requested: bool = False,
                 log_texts: list[str] | None = None) -> dict:
    """{"number": n or None, "closing": bool, "full_reviews": N or None, "since": commit of the newest review,
    "history": earlier reviews oldest first, each finding with its recorded disposition (closing reviews only)}."""
    limit = full_reviews(cfg)
    if pr is None or prior is None:
        return {"number": None, "closing": False, "full_reviews": limit, "since": "", "history": []}
    number = len(prior) + 1
    closing = bool(limit) and number > limit and not full_requested
    history = []
    if closing:
        for p in reversed(prior):
            known = dispositions(log_texts or [], p["name"])
            history.append({"name": p["name"], "reviewer": p.get("reviewer", ""), "commit": p["commit"],
                            "findings": [dict(f, disposition=known.get(str(f.get("id")), "not answered"))
                                         for f in p["findings"] if isinstance(f, dict)]})
        if sum(len(h["findings"]) for h in history) > MAX_LISTED_FINDINGS:
            closing, history = False, []           # too much to list: review it fully rather than narrowly
    return {"number": number, "closing": closing, "full_reviews": limit,
            "since": prior[0]["commit"] if prior else "", "history": history}


def closing_task(info: dict, pr: int) -> str:
    """The extra instructions a closing review gets, ahead of the material, with every earlier finding listed."""
    since = (f" The newest earlier review read commit `{info['since']}`: `git diff {info['since']}..HEAD` shows what "
             "changed since." if info.get("since") else "")
    lines = []
    for h in info.get("history") or []:
        lines.append(f"- `{h['name']}` ({h.get('reviewer') or 'reviewer'}, commit `{(h.get('commit') or '?')[:12]}`):"
                     + ("" if h["findings"] else " no findings"))
        for f in h["findings"]:
            where = f"{f.get('file', '?')}" + (f":{f['line_start']}" if f.get("line_start") else "")
            title = " ".join(str(f.get("title", "")).split())[:160]
            lines.append(f"  - {f.get('id', '?')} `{f.get('severity', '?')}` {title} ({where}) — recorded: "
                         f"{f['disposition']}")
    listed = "\n".join(lines) or "- (none)"
    return (f"This is review {info['number']} of PR #{pr}. This project gives a PR {info['full_reviews']} full "
            f"reviews; from then on a review is a *closing review* (REVIEW.md).{since}\n\n"
            "Earlier reviews of this PR and their findings, with what the decision logs record for each (from this "
            "PR's branch and from main). A recorded decision is what was proposed or decided, not proof that it "
            "holds: check it against the code.\n" + listed + "\n\n"
            "In a closing review:\n"
            "- Check every earlier finding above: is it fixed in the code now, still open, or settled by a recorded "
            "owner decision? Report any that is still open, at its severity. \"not answered\" means nobody has "
            "responded to it.\n"
            "- Check the fixes made since the earlier reviews, the code those fixes touch, and regressions they "
            "cause. Report any problem there at the severity it deserves.\n"
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


def round_for(root: Path, cfg: dict, pr: int | None, full_requested: bool = False,
              trusted: Path | None = None) -> dict:
    """The round of a PR review in checkout `root` (the PR's head, which holds the archive refs). Only reads the
    archive when the project has opted in. Dispositions come from the decision log on the PR's branch (where fix-PR
    rows land before the PR merges) and on main (`trusted`)."""
    if pr is None or full_reviews(cfg) is None:
        return {"number": None, "closing": False, "full_reviews": full_reviews(cfg), "since": "", "history": []}
    prior = prior_reviews(archive_history(root), pr, lambda name: read_record(root, name))
    log = cfg.get("decision_log", "reviews/decisions.md")
    texts = []
    for base in ([trusted] if trusted else []) + [root]:          # main first: the PR branch's rows win
        path = Path(base) / log
        if path.is_file():
            texts.append(path.read_text(errors="replace"))
    return review_round(cfg, pr, prior, full_requested, texts)
