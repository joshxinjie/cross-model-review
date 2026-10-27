"""Validate reviewer output against review/schema.json, plus checks a schema can't express.

A small validator for the subset of JSON Schema the review schema uses, so the harness needs no new dependency.
"""

import json
import re
from pathlib import Path

SEVERITY_ORDER = ["critical", "major", "minor", "nit", "question"]
PR_VERDICTS = {"approve", "approve_with_nits", "changes_needed"}
PROJECT_VERDICTS = {"healthy", "attention", "at_risk"}


def _type_ok(value, t: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }[t]


def schema_errors(value, schema: dict, root_schema: dict | None = None, path: str = "$") -> list[str]:
    root_schema = root_schema or schema
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/"), f"only local refs supported: {ref}"
        target = root_schema
        for part in ref[2:].split("/"):
            target = target[part]
        return schema_errors(value, target, root_schema, path)
    errs = []
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not one of {schema['enum']}")
    if "type" in schema and not _type_ok(value, schema["type"]):
        return errs + [f"{path}: expected {schema['type']}, got {type(value).__name__}"]
    if isinstance(value, str):
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']} characters ({len(value)})")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if _type_ok(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: above {schema['maximum']}")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items ({len(value)})")
        if "items" in schema:
            for k, v in enumerate(value):
                errs += schema_errors(v, schema["items"], root_schema, f"{path}[{k}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errs.append(f"{path}: missing required field {key!r}")
        props = schema.get("properties", {})
        for key, v in value.items():
            if key in props:
                errs += schema_errors(v, props[key], root_schema, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected field {key!r}")
    return errs


def derive_verdict(scope: str, findings: list[dict]) -> str:
    """The verdict REVIEW.md's rules give for these findings."""
    sev = {f.get("severity") for f in findings}
    if scope == "pr":
        if sev & {"critical", "major"}:
            return "changes_needed"
        return "approve_with_nits" if sev & {"minor"} else "approve"
    if "critical" in sev:
        return "at_risk"
    return "attention" if "major" in sev else "healthy"


def file_part(ref: str) -> str:
    """'METHODOLOGY.md#v1' or 'METHODOLOGY.md § v1' -> 'METHODOLOGY.md'."""
    return re.split(r"[#§ ]", ref.strip(), maxsplit=1)[0]


def semantic_errors(review: dict, scope: str, root: Path) -> list[str]:
    """Problems a retry should fix. Verdict mismatches are not errors: the harness corrects them (see run.py)."""
    errs = []
    if review.get("scope") != scope:
        errs.append(f"$.scope: must be {scope!r}")
    allowed = PR_VERDICTS if scope == "pr" else PROJECT_VERDICTS
    if review.get("verdict") not in allowed:
        errs.append(f"$.verdict: {review.get('verdict')!r} is not a {scope}-scope verdict ({sorted(allowed)})")
    ids = [f.get("id") for f in review.get("findings", [])]
    if len(ids) != len(set(ids)):
        errs.append("$.findings: ids must be unique")
    for k, f in enumerate(review.get("findings", [])):
        where = f"$.findings[{k}]"
        if "line_end" in f and "line_start" not in f:
            errs.append(f"{where}: line_end given without line_start")
        if "line_end" in f and "line_start" in f and f["line_end"] < f["line_start"]:
            errs.append(f"{where}: line_end before line_start")
        target = file_part(f.get("file", ""))
        if target and not (root / target).exists():
            errs.append(f"{where}.file: {target!r} does not exist in the repo")
    return errs


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a model reply (bare, or in a ```json fence)."""
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text[text.find("{"): text.rfind("}") + 1]
    if not candidate:
        raise ValueError("no JSON object found in the reply")
    return json.loads(candidate)
