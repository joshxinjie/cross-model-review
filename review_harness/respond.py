"""Author response to a cross-model review (`/respond`, review/RESPOND.md).

The author model answers each still-undecided finding of one review, edits the PR checkout to apply the fixes it
accepts, and returns its decisions. This module checks the answers, undoes any edit to the review machinery, writes
the decision rows into reviews/decisions.md itself, and renders a summary. The workflow then commits the result to a
new branch and opens a pull request into the reviewed PR's branch: nothing counts until the owner merges it.

Example (from a checkout of the PR, with the harness from main on PYTHONPATH):
  REVIEW_PROJECT_ROOT=<main checkout> python -m review_harness.respond --work-dir . --review-file review.json --pr 31 --base main \
      --fixed-in respond/pr31-2026-10-14 --summary-out summary.md --out responses.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import (ROOT, author_schema_path, footer, get_author, load_config, protected_paths, scope_for,
                     today_sgt)
from .providers.base import Provider
from .prompt import retry_message
from .run import report_error
from .validate import schema_errors

ICON = {"accept": "✅", "modify": "🔧", "reject": "✋", "defer": "⏳"}


# ---- decision log ---------------------------------------------------------------------------------------------------
# Row IDs follow the convention already in reviews/decisions.md: PR<n>-F<k> for a PR's first review, PR<n>-<round>-F<k>
# for later rounds; project reviews use PROJ-<date>[-<round>]-F<k>. The review cell links the review file, which is
# copied into reviews/ next to the log.

FINDING_CELL = re.compile(r"^(F\d{1,2})\b")


def cell(text: str, limit: int = 300) -> str:
    """One table cell: no pipes or line breaks, trimmed."""
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def table_rows(log_text: str) -> list[list[str]]:
    rows = []
    for line in log_text.splitlines():
        if not line.startswith("|") or line.startswith("| ID |") or line.startswith("|---"):
            continue
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def mentions(review_cell: str, review_name: str) -> bool:
    return re.search(rf"(?<![\w.-]){re.escape(review_name)}(?![\w.-])", review_cell) is not None


def decided(log_text: str, review_name: str) -> set[str]:
    """Finding IDs of this review already in the log (any row format: plain or linked review cell)."""
    out = set()
    for cells in table_rows(log_text):
        if len(cells) >= 4 and mentions(cells[2], review_name) and (m := FINDING_CELL.match(cells[3])):
            out.add(m.group(1))
    return out


def row_prefix(log_text: str, review_name: str) -> str:
    """ID prefix for this review: reuse the one already in the log, else the next round for its PR or project."""
    rows = table_rows(log_text)
    for cells in rows:
        if len(cells) >= 4 and mentions(cells[2], review_name) and re.search(r"-F\d+$", cells[0]):
            return re.sub(r"-F\d+$", "", cells[0])
    if m := re.search(r"-pr(\d+)-", review_name):
        base, pattern = f"PR{m.group(1)}", re.compile(rf"^PR{m.group(1)}(?:-(\d+))?-F\d+$")
    else:
        date = review_name[:10]
        base, pattern = f"PROJ-{date}", re.compile(rf"^PROJ-{date}(?:-(\d+))?-F\d+$")
    rounds = {int(m.group(1) or 1) for cells in rows if (m := pattern.match(cells[0]))}
    return base if not rounds else f"{base}-{max(rounds) + 1}"


def decision_rows(responses: list[dict], envelope: dict, review_name: str, prefix: str, date: str,
                  fixed_in: str) -> list[str]:
    findings = {f["id"]: f for f in envelope["review"]["findings"]}
    rows = []
    for r in sorted(responses, key=lambda r: int(r["finding_id"][1:]), reverse=True):   # newest-first table
        f = findings[r["finding_id"]]
        # Full text: the schemas cap titles (120), reasons (600) and changes (300), so nothing is cut here.
        where = {"accept": fixed_in, "modify": fixed_in, "reject": "—",
                 "defer": cell(r["changes"], 400)}[r["decision"]]
        rows.append(f"| {prefix}-{r['finding_id']} | {date} | [{review_name}]({review_name}) (copy of "
                    f"`reviewer/archive`) | {r['finding_id']}: {cell(f['title'], 200)} | "
                    f"{envelope['meta']['reviewer']} | {f['severity']} | {r['decision']} | {cell(r['reason'], 800)} | "
                    f"{where} |")
    return rows


def insert_rows(log_text: str, rows: list[str]) -> str:
    """New rows go at the top of the table, right under the header separator."""
    lines = log_text.splitlines()
    for k, line in enumerate(lines):
        if line.startswith("| ID |") and k + 1 < len(lines) and lines[k + 1].startswith("|---"):
            return "\n".join(lines[: k + 2] + rows + lines[k + 2:]) + "\n"
    raise ValueError("decision log table header not found")


# ---- checks ---------------------------------------------------------------------------------------------------------

def response_errors(resp: dict, schema: dict, pending: list[str]) -> list[str]:
    errs = schema_errors(resp, schema)
    if errs:
        return errs
    ids = [r["finding_id"] for r in resp["responses"]]
    missing = [i for i in pending if i not in ids]
    extra = [i for i in ids if i not in pending]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if missing:
        errs.append(f"no answer for: {', '.join(missing)}")
    if extra:
        errs.append(f"answers for findings not asked about: {', '.join(extra)}")
    if dup:
        errs.append(f"more than one answer for: {', '.join(dup)}")
    return errs


def git(work_dir: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(work_dir), *args], check=True, capture_output=True, text=True).stdout


def status_entries(work_dir: Path) -> list[tuple[str, str, str | None]]:
    """(XY status, path, original path for a rename or copy) from `git status -z`, which keeps names exact."""
    raw = subprocess.run(["git", "-C", str(work_dir), "status", "--porcelain", "-z", "--untracked-files=all"],
                         check=True, capture_output=True).stdout.decode()
    items, out, k = raw.split("\0"), [], 0
    while k < len(items):
        entry = items[k]
        k += 1
        if not entry:
            continue
        xy, path, orig = entry[:2], entry[3:], None
        if "R" in xy or "C" in xy:                  # -z puts the original path in the next field
            orig, k = items[k], k + 1
        out.append((xy, path, orig))
    return out


def in_head(work_dir: Path, path: str) -> bool:
    return subprocess.run(["git", "-C", str(work_dir), "cat-file", "-e", f"HEAD:{path}"],
                          capture_output=True).returncode == 0


def revert_protected(work_dir: Path, protected: list[str], allowed: list[str] | None = None) -> list[str]:
    """Undo any change the author made to the review machinery, or (with `allowed`, the PR's scope) to any file
    outside the scope's globs; return what was undone. A rename counts if either side is affected (moving a
    protected file out would otherwise delete it from the PR), and is undone whole."""
    import fnmatch

    def is_protected(path):
        if path is None:
            return False
        if any(path == p or path.startswith(p) or fnmatch.fnmatchcase(path, p + ("*" if p.endswith("/") else ""))
               for p in protected):        # plain prefixes, or globs such as strategies/*/results/
            return True
        return allowed is not None and not any(fnmatch.fnmatchcase(path, g) for g in allowed)

    def restore(path):
        if in_head(work_dir, path):
            git(work_dir, "checkout", "HEAD", "--", path)
        else:
            subprocess.run(["git", "-C", str(work_dir), "rm", "-q", "--cached", "--ignore-unmatch", "--", path],
                           capture_output=True)
            (work_dir / path).unlink(missing_ok=True)

    reverted = []
    for xy, path, orig in status_entries(work_dir):
        touched = [x for x in (orig, path) if x is not None]
        if not any(is_protected(x) for x in touched):
            continue
        for x in touched:
            restore(x)
            reverted.append(x)
    return reverted


# ---- prompt and summary ---------------------------------------------------------------------------------------------

def build_prompt(root: Path, cfg: dict, envelope: dict, pending: list[str], pr: int | None, base: str,
                 author: dict | None = None, allowed: list[str] | None = None) -> tuple[str, str]:
    author = author or get_author(cfg)
    instructions = (root / author.get("instructions", "review/RESPOND.md")).read_text()
    schema = json.loads(author_schema_path(root, author).read_text())
    system = (instructions.rstrip() + "\n\n## Output format (mandatory)\n\nReturn one JSON object matching this "
              "schema, answering exactly these finding IDs: " + ", ".join(pending) + ".\n\n"
              + json.dumps(schema, indent=1))
    findings = [f for f in envelope["review"]["findings"] if f["id"] in pending]
    if envelope["review"].get("scope") == "project":
        target = "the project (not a single pull request)"
        where = ("The repository is checked out at main plus the review record. The findings concern the project as "
                 "it stands; fix them in place.\n\n")
    else:
        target = f"pull request #{pr}" if pr else "the project"
        where = (f"The repository is checked out at the PR's head; `git diff origin/{base}...HEAD` shows the PR's "
                 "changes.\n\n")
    if allowed is not None:
        where += ("In this pull request you may only change files matching: " + ", ".join(f"`{g}`" for g in allowed)
                  + ". Other edits are undone; propose those changes in your reason instead.\n\n")
    user = (f"A reviewer ({envelope['meta']['model']}) reviewed {target}. Its verdict: {envelope['review']['verdict']}. "
            f"Its summary: {envelope['review']['summary']}\n\n" + where +
            f"Findings to answer ({len(findings)}):\n\n{json.dumps(findings, indent=1, ensure_ascii=False)}\n\n"
            "Work through them, apply the fixes you accept, run the tests, then return the JSON object.")
    return system, user


def render_summary(resp: dict, envelope: dict, review_name: str, reverted: list[str], already: list[str],
                   pr: int | None, author_model: str, decision_log: str = "reviews/decisions.md",
                   closing: str = "") -> str:
    counts = {d: sum(1 for r in resp["responses"] if r["decision"] == d) for d in ICON}
    head = (f"### Author response to the cross-model review\n"
            f"Author `{author_model}` answered {len(resp['responses'])} finding"
            f"{'' if len(resp['responses']) == 1 else 's'} of `{review_name}`"
            f"{f' on #{pr}' if pr else ''}: "
            + " · ".join(f"{ICON[d]} {counts[d]} {d}" for d in ICON if counts[d]) + "\n\n"
            + resp["summary"] + "\n")
    t = resp["tests"]
    tests = ("✅ tests pass" if t["passed"] else "❌ tests fail") if t["ran"] else "⚠️ tests not run"
    rows = "\n".join(f"| {r['finding_id']} | {ICON[r['decision']]} {r['decision']} | {cell(r['reason'], 200)} |"
                     for r in sorted(resp["responses"], key=lambda r: int(r["finding_id"][1:])))
    notes = []
    if already:
        notes.append("already decided earlier, skipped: " + ", ".join(already))
    if reverted:
        notes.append("edits the author may not make (review machinery, or outside this PR's scope) were undone: "
                     + ", ".join(reverted))
    return (head + f"\n**{tests}** — {cell(t['detail'], 200)}\n\n"
            "<details><summary>Each finding</summary>\n\n| Finding | Decision | Reason |\n|---|---|---|\n"
            + rows + "\n</details>\n\n"
            + ("<sub>" + " · ".join(notes) + "</sub>\n\n" if notes else "")
            + f"Merging this pull request accepts these decisions; they are logged in `{decision_log}`. "
            "Close it to reject them all, or comment to change any.\n" + (f"\n{closing}\n" if closing else ""))


# ---- run ------------------------------------------------------------------------------------------------------------

def respond(root: Path, cfg: dict, provider: Provider, work_dir: Path, envelope: dict, review_name: str,
            pr: int | None, base: str, fixed_in: str, date: str | None = None, author: dict | None = None,
            head_ref: str | None = None, title: str | None = None) -> dict:
    """Returns {"status": "done" | "nothing" | "invalid", ...}; on "done" the decision log in work_dir is updated."""
    if "invalid" in envelope.get("meta", {}) or not envelope.get("review"):
        raise ValueError(f"{review_name} failed validation; there are no findings to answer")
    log_path = work_dir / cfg["decision_log"]
    log_text = log_path.read_text()
    already = sorted(decided(log_text, review_name), key=lambda i: int(i[1:]))
    pending = [f["id"] for f in envelope["review"]["findings"] if f["id"] not in already]
    if not pending:
        return {"status": "nothing", "already": already}
    author = author or get_author(cfg)
    schema = json.loads(author_schema_path(root, author).read_text())
    allowed = scope_for(cfg, head_ref, title)
    system, user = build_prompt(root, cfg, envelope, pending, pr, base, author, allowed)
    messages = [{"role": "user", "content": user}]
    errors, resp = ["not run"], None
    for _ in range(2):                      # one retry: the author's edits stay; only its answer is corrected
        c = provider.complete(system, messages, cfg["limits"]["max_output_tokens"])
        try:
            resp = json.loads(c.text)
            errors = response_errors(resp, schema, pending)
        except json.JSONDecodeError as e:
            errors = [f"reply is not valid JSON: {e}"]
        if not errors:
            break
        messages += [{"role": "assistant", "content": c.text}, {"role": "user", "content": retry_message(errors)}]
    reverted = revert_protected(work_dir, cfg_protected(cfg), allowed)
    if errors:
        return {"status": "invalid", "errors": errors, "reverted": reverted}
    rows = decision_rows(resp["responses"], envelope, review_name, row_prefix(log_text, review_name),
                         date or today_sgt(), fixed_in)
    log_path.write_text(insert_rows(log_text, rows))
    copy = log_path.parent / review_name          # the rows link to it, as earlier rows do
    if not copy.exists():
        copy.write_text(json.dumps(envelope, indent=1, ensure_ascii=False) + "\n")
    return {"status": "done", "response": resp, "rows": rows, "reverted": reverted, "already": already,
            "summary": render_summary(resp, envelope, review_name, reverted, already, pr, author["model"],
                                      cfg["decision_log"], footer(cfg))}


def cfg_protected(cfg: dict) -> list[str]:
    return protected_paths(cfg)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-dir", required=True, help="checkout of the PR head the author edits")
    ap.add_argument("--review-file", required=True, help="the review envelope (JSON) to answer")
    ap.add_argument("--review-name", help="its file name in reviews/ (default: the file's own name)")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--base", default="main")
    ap.add_argument("--fixed-in", required=True, help="branch the fixes are committed to")
    ap.add_argument("--summary-out", required=True)
    ap.add_argument("--out", help="write the author's decisions (JSON) here")
    ap.add_argument("--error-file")
    ap.add_argument("--author", help="who built the work (review/config.yaml authors; default: default_author)")
    ap.add_argument("--head-ref", help="the reviewed PR's branch (for review/config.yaml scopes)")
    ap.add_argument("--title", help="the reviewed PR's title (for review/config.yaml scopes)")
    args = ap.parse_args(argv)
    try:
        from .providers.claude_code import ClaudeCodeProvider
        from .providers.codex import CodexProvider
        cfg = load_config(ROOT)
        author = get_author(cfg, args.author)
        work_dir = Path(args.work_dir).resolve()
        envelope = json.loads(Path(args.review_file).read_text())
        name = args.review_name or Path(args.review_file).name
        schema = json.loads(author_schema_path(ROOT, author).read_text())
        from .progress import Progress
        progress = Progress(f"Author response by `{author['model']}` to `{name}`")
        if author["provider"] == "codex":
            provider = CodexProvider(author, cwd=ROOT, work_dir=work_dir, mode="respond", schema=schema)
        elif author["provider"] == "claude-code":
            provider = ClaudeCodeProvider(author, cwd=ROOT, mode="respond", work_dir=work_dir, schema=schema)
        else:
            raise ValueError(f"author provider {author['provider']!r} cannot answer reviews")
        provider.on_step = progress.step
        progress.start()
        result = respond(ROOT, cfg, provider, work_dir, envelope, name, args.pr, args.base, args.fixed_in,
                         author=author, head_ref=args.head_ref, title=args.title)
    except Exception as e:  # noqa: BLE001 - one-line reason for the PR, full traceback in the log
        if "progress" in locals():
            progress.finish(False, "stopped with an error (reason below)")
        report_error(args.error_file, f"{type(e).__name__}: {e}")
        raise
    progress.finish(result["status"] != "invalid",
                    {"done": "decisions ready; the fix PR follows", "nothing": "nothing left to answer",
                     "invalid": "its answer failed validation (reason below)"}[result["status"]])
    if result["status"] == "nothing":
        Path(args.summary_out).write_text(f"ℹ️ Every finding of `{name}` is already in the decision log "
                                          f"({', '.join(result['already'])}); nothing to answer.\n")
        return 3
    if result["status"] == "invalid":
        report_error(args.error_file, "The author's answer failed validation after one retry: "
                     + "; ".join(result["errors"][:5]))
        return 2
    Path(args.summary_out).write_text(result["summary"])
    if args.out:
        Path(args.out).write_text(json.dumps({"review": name, "author": author["model"], "date": today_sgt(),
                                              "harness": os.environ.get("REVIEW_HARNESS_COMMIT", ""),
                                              "response": result["response"], "reverted": result["reverted"]},
                                             indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(result["rows"]), "reverted": result["reverted"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
