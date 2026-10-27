"""Run one cross-model review and save it to reviews/.

Examples (from a project's checkout, with this repository on PYTHONPATH):
  python -m review_harness.run --scope pr --base origin/main --head HEAD --pr 25 --dry-run
  python -m review_harness.run --scope project --areas src/ docs/plan.md
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import ROOT, get_author, get_reviewer, load_config, schema_path, today_sgt
from .context import build_pr_pack, build_project_pack
from .prompt import build_prompt, retry_message
from .providers import Provider, get_provider
from .validate import derive_verdict, extract_json, schema_errors, semantic_errors

MAX_ATTEMPTS = 2
REDACT = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})")     # first try plus one retry with the validation errors


def check(reply: str, scope: str, schema: dict, root: Path) -> tuple[dict | None, list[str]]:
    """root: the checkout under review (findings must name files that exist there)."""
    try:
        review = extract_json(reply)
    except ValueError as e:          # includes json.JSONDecodeError
        return None, [f"reply is not valid JSON: {e}"]
    errors = schema_errors(review, schema)
    if errors:                       # the semantic checks assume a well-typed review: retry on these first
        return review, errors
    try:
        return review, semantic_errors(review, scope, root)
    except Exception as e:  # noqa: BLE001 - a malformed reply must reach the retry, never end the run
        return review, [f"reply could not be checked ({type(e).__name__}: {e}); follow the schema exactly"]


def run_review(root: Path, cfg: dict, reviewer: dict, provider: Provider, pack: dict, repo: Path | None = None) -> dict:
    """Call the reviewer, validate, retry once, correct the verdict; return the envelope (not yet saved).
    root holds the harness (instructions, schema); repo is the checkout under review (default: root)."""
    schema = json.loads(schema_path(root, cfg).read_text())
    system, user = build_prompt(root, cfg, pack)
    messages = [{"role": "user", "content": user}]
    usage_in = usage_out = 0
    review, errors = None, ["not run"]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        c = provider.complete(system, messages, cfg["limits"]["max_output_tokens"])
        usage_in += c.input_tokens
        usage_out += c.output_tokens
        review, errors = check(c.text, pack["scope"], schema, repo or root)
        if not errors:
            break
        messages += [{"role": "assistant", "content": c.text}, {"role": "user", "content": retry_message(errors)}]
    meta = {
        "reviewer": reviewer["name"], "provider": reviewer["provider"], "model": reviewer["model"],
        "scope": pack["scope"], "date": today_sgt(),
        "input_tokens": usage_in, "output_tokens": usage_out, "attempts": attempt,
        "context_files": pack["files"], "context_dropped": pack["dropped"], "context_tokens_est": pack["tokens"],
    }
    if errors:
        meta["invalid"] = errors
        return {"meta": meta, "review": review}
    expected = derive_verdict(pack["scope"], review["findings"])
    if review["verdict"] != expected:
        meta["verdict_adjusted_from"] = review["verdict"]
        review["verdict"] = expected
    review["findings"].sort(key=lambda f: ["critical", "major", "minor", "nit", "question"].index(f["severity"]))
    return {"meta": meta, "review": review}


def output_path(root: Path, date: str, scope_tag: str, reviewer: str, taken=frozenset()) -> Path:
    """A name used neither in reviews/ nor on the archive branch (taken), so no record is ever overwritten."""
    base = root / "reviews" / f"{date}-{scope_tag}-{reviewer}.json"
    k = 2
    while base.exists() or base.name in taken:
        base = root / "reviews" / f"{date}-{scope_tag}-{reviewer}-{k}.json"
        k += 1
    return base


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", choices=["pr", "project"], required=True)
    ap.add_argument("--reviewer", help="name in review/config.yaml (default: the author's default reviewer)")
    ap.add_argument("--author", help="who built the work, from review/config.yaml authors (default: default_author)")
    ap.add_argument("--base", default="origin/main", help="pr scope: base ref")
    ap.add_argument("--head", default="HEAD", help="pr scope: head ref")
    ap.add_argument("--pr", type=int, help="pr scope: pull request number (for the file name and posting)")
    ap.add_argument("--title", default="", help="pr scope: PR title")
    ap.add_argument("--body-file", help="pr scope: file with the PR description")
    ap.add_argument("--areas", nargs="*", help="project scope: paths or globs (default: config default_areas)")
    ap.add_argument("--dry-run", action="store_true", help="build the prompt and report its size; no API call")
    ap.add_argument("--out", help="write the envelope here instead of reviews/")
    ap.add_argument("--error-file", help="on failure, write a short reason here (the workflow posts it on the PR)")
    ap.add_argument("--repo-dir", help="checkout under review, left unmodified (default: the harness's own repo). "
                                       "The harness, instructions, config and decision log always come from the "
                                       "harness's checkout.")
    args = ap.parse_args(argv)
    try:
        return _main(args)
    except Exception as e:          # noqa: BLE001 - report any failure in one line, then re-raise for the log
        report_error(args.error_file, f"{type(e).__name__}: {e}")
        raise


def report_error(path: str | None, message: str) -> None:
    """Write a short, secret-free reason for the failure. API keys are sent only in headers, never echoed."""
    message = REDACT.sub("[redacted]", message)[:800]
    if path:
        Path(path).write_text(message + "\n")
    print(message, file=sys.stderr)


def _main(args) -> int:
    root = ROOT                                         # trusted harness (main)
    repo = Path(args.repo_dir).resolve() if args.repo_dir else root
    trusted = root if repo != root else None
    cfg = load_config(root)
    # PR reviews name the PR's author; project reviews have none and use the top-level default reviewer.
    reviewer = get_reviewer(cfg, args.reviewer, get_author(cfg, args.author) if args.author else None)
    if args.scope == "pr":
        body = Path(args.body_file).read_text() if args.body_file else ""
        pack = build_pr_pack(repo, cfg, args.base, args.head, args.title, body, trusted)
        scope_tag = f"pr{args.pr}" if args.pr else "pr"
    else:
        pack = build_project_pack(repo, cfg, args.areas, trusted)
        scope_tag = "project"

    if args.dry_run:
        system, user = build_prompt(root, cfg, pack)
        print(json.dumps({"reviewer": reviewer["name"], "model": reviewer["model"], "scope": pack["scope"],
                          "files": len(pack["files"]), "dropped": pack["dropped"],
                          "prompt_tokens_est": (len(system) + len(user)) // 4}, indent=1))
        return 0

    from .progress import Progress
    progress = Progress(f"Cross-model review by {reviewer['name']} (`{reviewer['model']}`)")
    provider = get_provider(reviewer, work_dir=repo)
    if hasattr(provider, "on_step"):
        provider.on_step = progress.step
    progress.start()
    try:
        envelope = run_review(root, cfg, reviewer, provider, pack, repo)
    except Exception:
        progress.finish(False, "stopped with an error (reason below)")
        raise
    if "invalid" in envelope["meta"]:
        progress.finish(False, "its output failed validation (reason below)")
    else:
        progress.finish(True, f"verdict `{envelope['review']['verdict']}`, "
                              f"{len(envelope['review']['findings'])} findings; the review follows")
    envelope["meta"]["pr"] = args.pr
    if os.environ.get("REVIEW_HARNESS_COMMIT"):         # which harness ran the review (set by the workflow)
        envelope["meta"]["harness"] = os.environ["REVIEW_HARNESS_COMMIT"]
    envelope["meta"]["commit"] = subprocess.run(["git", "-C", str(repo), "rev-parse", args.head if args.scope == "pr"
                                                 else "HEAD"], capture_output=True, text=True).stdout.strip()
    from .gate import archive_listing
    taken = {Path(f).name for f in archive_listing(repo)}
    out = Path(args.out) if args.out else output_path(repo, envelope["meta"]["date"], scope_tag, reviewer["name"],
                                                      taken)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(envelope, indent=1, ensure_ascii=False) + "\n")
    print(out)
    if "invalid" in envelope["meta"]:
        report_error(args.error_file, "The reviewer's output failed validation after one retry: "
                     + "; ".join(envelope["meta"]["invalid"][:5]))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
