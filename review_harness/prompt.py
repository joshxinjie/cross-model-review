"""Build the system and user messages every reviewer model receives (identical across providers)."""

import json
from pathlib import Path

from .config import schema_path

OUTPUT_RULES = """\
## Output format (mandatory)

Reply with ONE JSON object that validates against the schema below, and nothing else: no prose before or after,
no comments inside the JSON. Use scope "{scope}". Every `file` must be a repo-relative path that appears in the
material provided (a document path may be followed by "#section"). Line numbers refer to the file as given (for a
pull request, the new version of the file).

Schema:
{schema}
"""

SCOPE_TASK = {
    "pr": "Review this pull request (scope `pr`). The diff is the subject; the other files are context.",
    "project": "Review the project as given (scope `project`). Focus on the areas included; prioritise what could "
               "change a result, a verdict or a decision.",
}


def build_prompt(root: Path, cfg: dict, pack: dict) -> tuple[str, str]:
    instructions = (root / cfg["instructions"]).read_text()
    schema = json.loads(schema_path(root, cfg).read_text())
    system = (instructions.rstrip() + "\n\n"
              + OUTPUT_RULES.format(scope=pack["scope"], schema=json.dumps(schema, indent=1)))
    dropped = ""
    if pack["dropped"]:
        dropped = ("\nThese files were left out to fit the size limit; do not assume their contents: "
                   + ", ".join(pack["dropped"]) + "\n")
    user = (f"{SCOPE_TASK[pack['scope']]}\n{dropped}\n"
            f"Material ({len(pack['files'])} items):\n\n{pack['text']}\n\n"
            "Return the JSON object now.")
    return system, user


def retry_message(errors: list[str]) -> str:
    listed = "\n".join(f"- {e}" for e in errors[:30])
    return ("Your reply did not pass validation:\n" + listed
            + "\n\nReturn the corrected JSON object only, keeping your findings unless an error requires a change.")
