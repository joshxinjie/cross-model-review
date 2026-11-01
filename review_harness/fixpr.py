"""Decide whether the /respond fix PR opens as a draft, and lay out its description.

The project's `check` command (respond.yml input) runs after the author's changes. Its own exit code decides: only an
exit code of exactly 0 opens a normal pull request. A failed check, no configured check, a check that did not finish
(no exit code recorded) and anything unreadable all open a draft, with the reason first in the description. A draft
is never a passing check, and a normal PR says only that the configured check passed: the author's per-finding
verification (and its gaps) is reported separately, in the author's summary.

Example (respond.yml):
  python -m review_harness.fixpr --check-configured "$CONFIGURED" --check-code "$CHECK_CODE" \
      --summary "$RUNNER_TEMP/summary.md" --check-output "$RUNNER_TEMP/check.txt" --commit "$SHA" \
      --body-out "$RUNNER_TEMP/body.md"            # prints draft=true|false and a reason for $GITHUB_OUTPUT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TAIL_LINES = 60


def check_status(configured: bool, code: str | None) -> dict:
    """{"draft": bool, "state": "passed" | "failed" | "not_configured" | "unknown", "headline": str}."""
    code = (code or "").strip()
    if not configured:
        return {"draft": True, "state": "not_configured",
                "headline": "**⚠️ No configured check ran** (the workflow's `check` input is empty), so whether the "
                            "author's changes pass the project's checks is unknown. Opened as a draft."}
    if code == "0":
        return {"draft": False, "state": "passed",
                "headline": "**✅ Configured checks passed** after the author's changes (exit 0)."}
    if code.isdigit():
        return {"draft": True, "state": "failed",
                "headline": f"**❌ Configured checks failed** after the author's changes (exit {code}). "
                            "Opened as a draft: look before merging."}
    return {"draft": True, "state": "unknown",
            "headline": "**⚠️ Configured checks did not finish** (no exit code was recorded), so their result is "
                        "unknown. Opened as a draft."}


def check_block(output: str) -> str:
    tail = "\n".join(output.rstrip("\n").splitlines()[-TAIL_LINES:])
    return ("<details><summary>Check output (last 60 lines)</summary>\n\n```\n" + tail.replace("```", "`​``")
            + "\n```\n</details>\n")


def compose(summary: str, status: dict, check_output: str | None, commit: str = "") -> str:
    """The fix PR's description: a check that did not pass leads; a passing one follows the author's summary."""
    where = f"Checks ran on the author's changes as committed in `{commit[:12]}`.\n" if commit else ""
    block = check_block(check_output) if check_output and status["state"] in ("passed", "failed") else ""
    check = status["headline"] + "\n\n" + (where + "\n" if where else "") + block
    if status["draft"]:
        return check.rstrip() + "\n\n---\n\n" + summary.rstrip() + "\n"
    return summary.rstrip() + "\n\n" + check.rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check-configured", required=True, choices=["true", "false"])
    ap.add_argument("--check-code", default="", help="the check command's exit code ('' if none was recorded)")
    ap.add_argument("--summary", required=True, help="the author's summary (markdown)")
    ap.add_argument("--check-output", help="the check's captured output, if it ran")
    ap.add_argument("--commit", default="", help="the commit the fix PR's changes are in")
    ap.add_argument("--body-out", required=True)
    args = ap.parse_args(argv)
    status = check_status(args.check_configured == "true", args.check_code)
    out = Path(args.check_output) if args.check_output else None
    output = out.read_text(errors="replace") if out and out.exists() else None
    Path(args.body_out).write_text(compose(Path(args.summary).read_text(), status, output, args.commit))
    print(f"draft={'true' if status['draft'] else 'false'}")
    print(f"state={status['state']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
