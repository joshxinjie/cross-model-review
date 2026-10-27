"""Turn a saved review into a phone-sized summary and inline PR comments, and post them to GitHub.

Example:
  PYTHONPATH=scripts python -m review_harness.post reviews/2026-10-14-pr25-fable.json \
      --repo owner/name --pr 25 --base origin/main --head HEAD --post
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

from .config import ROOT, footer, load_config
from .context import git
from .diff import parse_unified_diff
from .validate import file_part

ICON = {"approve": "✅", "approve_with_nits": "✅", "changes_needed": "❌",
        "healthy": "✅", "attention": "⚠️", "at_risk": "❌"}
SEV_ICON = {"critical": "🔴", "major": "🟠", "minor": "🟡", "nit": "⚪", "question": "❔"}


def location(f: dict) -> str:
    loc = f["file"]
    if "line_start" in f:
        loc += f":{f['line_start']}" + (f"-{f['line_end']}" if f.get("line_end", f["line_start"]) != f["line_start"]
                                         else "")
    return loc


def finding_body(f: dict) -> str:
    extra = f"\n\nChecklist: {f['checklist_item']}" if f.get("checklist_item") else ""
    revisits = f"\n\nRevisits decision {f['related_decision']}." if f.get("related_decision") else ""
    return (f"{SEV_ICON[f['severity']]} **{f['id']} · {f['severity']} · {f['area']}: {f['title']}**\n\n"
            f"{f['claim']}\n\n**Evidence:** {f['evidence']}\n\n**Suggested change:** {f['proposed_change']}"
            f"{extra}{revisits}\n\n<sub>Checked by {f['verified_by'].replace('_', ' ')}; "
            f"confidence {f['confidence']:.0%}</sub>")


def plan_comments(findings: list[dict], diff_map: dict) -> tuple[list[dict], list[dict]]:
    """Split findings into inline comments (on lines GitHub will accept) and the rest."""
    inline, rest = [], []
    for f in findings:
        path = file_part(f["file"])
        lines = diff_map.get(path, {}).get("commentable", set())
        start, end = f.get("line_start"), f.get("line_end", f.get("line_start"))
        if start is not None and start in lines:
            c = {"path": path, "line": end if end in lines else start, "side": "RIGHT", "body": finding_body(f)}
            if end in lines and end != start and all(n in lines for n in range(start, end + 1)):
                c.update(start_line=start, start_side="RIGHT")
            inline.append(c)
        else:
            rest.append(f)
    return inline, rest


def render_summary(envelope: dict, not_inline: list[dict] | None = None, decision_log: str = "reviews/decisions.md",
                   closing: str = "") -> str:
    meta, review = envelope["meta"], envelope["review"]
    findings = review["findings"]
    head = (f"### {ICON[review['verdict']]} Cross-model review: `{review['verdict']}`\n"
            f"Reviewer **{meta['reviewer']}** (`{meta['model']}`) · {len(findings)} finding"
            f"{'' if len(findings) == 1 else 's'}\n\n{review['summary']}\n")
    top = "".join(f"\n{SEV_ICON[f['severity']]} **{f['id']}** {f['title']} — `{location(f)}`" for f in findings[:3])
    parts = [head, top + "\n" if top else ""]
    if not_inline:
        parts.append("\n<details><summary>Findings not on changed lines ("
                     f"{len(not_inline)})</summary>\n\n"
                     + "\n\n---\n\n".join(f"`{location(f)}`\n\n{finding_body(f)}" for f in not_inline)
                     + "\n</details>\n")
    elif not_inline is None and findings:      # project scope: everything goes in the summary
        parts.append("\n<details><summary>All findings</summary>\n\n"
                     + "\n\n---\n\n".join(f"`{location(f)}`\n\n{finding_body(f)}" for f in findings)
                     + "\n</details>\n")
    notes = []
    if meta.get("verdict_adjusted_from"):
        notes.append(f"verdict corrected from `{meta['verdict_adjusted_from']}` by the severity rules")
    if meta.get("context_dropped"):
        notes.append("left out to fit the limit: " + ", ".join(meta["context_dropped"][:8]))
    notes.append(f"{meta['input_tokens']:,} in / {meta['output_tokens']:,} out tokens")
    parts.append("\n<sub>" + " · ".join(notes) + "</sub>\n\nComment `/respond` for the author's answer to each finding, "
                 f"as a fix PR you can merge or close. Decisions go in `{decision_log}`.\n"
                 + (f"\n{closing}\n" if closing else ""))
    return "".join(parts)


def post_pr_review(repo: str, pr: int, commit: str, body: str, comments: list[dict], token: str,
                   session: requests.Session | None = None) -> dict:
    """Post one COMMENT review (never APPROVE or REQUEST_CHANGES: the reviewer only suggests).

    If GitHub rejects the inline comments (422, e.g. a line outside the diff), retry with everything in the body.
    """
    s = session or requests.Session()
    url = f"https://api.github.com/repos/{repo}/pulls/{pr}/reviews"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    payload = {"commit_id": commit, "body": body, "event": "COMMENT", "comments": comments}
    r = s.post(url, json=payload, headers=headers, timeout=60)
    if r.status_code == 422 and comments:
        fallback = body + "\n\n<details><summary>Inline comments (GitHub rejected their positions)</summary>\n\n" \
            + "\n\n---\n\n".join(f"`{c['path']}:{c['line']}`\n\n{c['body']}" for c in comments) + "\n</details>\n"
        r = s.post(url, json={"commit_id": commit, "body": fallback, "event": "COMMENT"}, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("review", help="saved review envelope (reviews/*.json)")
    ap.add_argument("--repo", help="owner/name, for posting")
    ap.add_argument("--pr", type=int, help="pull request number, for posting")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--summary-out", help="write the summary markdown here")
    ap.add_argument("--post", action="store_true", help="post to the PR (needs GITHUB_TOKEN)")
    ap.add_argument("--repo-dir", help="checkout to read the diff from (default: the project root)")
    args = ap.parse_args(argv)

    envelope = json.loads(Path(args.review).read_text())
    cfg = load_config(ROOT)
    words = {"decision_log": cfg["decision_log"], "closing": footer(cfg)}
    repo_dir = Path(args.repo_dir) if args.repo_dir else ROOT
    if "invalid" in envelope["meta"] or envelope.get("review") is None:
        print("This review failed validation; nothing to post.", file=sys.stderr)
        return 2
    if envelope["review"]["scope"] == "pr":
        diff_map = parse_unified_diff(git(repo_dir, "diff", "--unified=3", f"{args.base}...{args.head}"))
        inline, rest = plan_comments(envelope["review"]["findings"], diff_map)
        summary = render_summary(envelope, rest, **words)
    else:
        inline, summary = [], render_summary(envelope, **words)
    if args.summary_out:
        Path(args.summary_out).write_text(summary)
    if args.post:
        token = os.environ.get("GITHUB_TOKEN") or sys.exit("GITHUB_TOKEN is not set")
        if not (args.repo and args.pr):
            sys.exit("--repo and --pr are needed to post")
        commit = envelope["meta"].get("commit") or git(repo_dir, "rev-parse", args.head).strip()
        result = post_pr_review(args.repo, args.pr, commit, summary, inline, token)
        print(result.get("html_url", "posted"))
    elif not args.summary_out:
        print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
