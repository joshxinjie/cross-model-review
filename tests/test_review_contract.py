"""Cross-model review contract (REVIEW.md): schema, config and docs must stay consistent."""

import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "tests" / "fixture"
SCHEMA = json.loads((REPO / "review_harness" / "schemas" / "review.json").read_text())
CONFIG = yaml.safe_load((ROOT / "review" / "config.yaml").read_text())
REVIEW_MD = (ROOT / "REVIEW.md").read_text()
FINDING = SCHEMA["$defs"]["finding"]["properties"]


def test_config_points_at_existing_files():
    for key in ("instructions", "decision_log"):
        assert (ROOT / CONFIG[key]).exists(), f"config {key} -> {CONFIG[key]} missing"
    for name, author in CONFIG["authors"].items():
        assert (ROOT / author["instructions"]).exists(), f"author {name} instructions missing"
    for scope in ("pr", "project"):
        for path in CONFIG["context"][scope]["always"]:
            assert (ROOT / path).exists(), f"context.{scope}.always -> {path} missing"


def test_default_reviewers_enabled_pinned_and_not_the_author():
    reviewers, authors = CONFIG["reviewers"], CONFIG["authors"]
    assert CONFIG["default_author"] in authors
    project_default = reviewers[CONFIG["default_reviewer"]]
    assert project_default["enabled"]
    assert all(project_default["model"] != a["model"] for a in authors.values()), "project default is an author"
    for name, a in authors.items():
        own = reviewers[a["default_reviewer"]]
        assert own["enabled"] and own["model"] != a["model"], f"author {name}'s default reviewer is itself"
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", a["secret"]), "secret must be a name, not a key"
    for name, r in reviewers.items():
        if r["enabled"]:
            assert r["model"], f"enabled reviewer {name} has no pinned model"
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", r["secret"]), "secret must be a name, not a key"


def test_every_schema_enum_is_documented_in_review_md():
    enums = (SCHEMA["properties"]["verdict"]["enum"] + FINDING["severity"]["enum"]
             + FINDING["verified_by"]["enum"])
    missing = [v for v in enums if f"`{v}`" not in REVIEW_MD]
    assert not missing, f"REVIEW.md does not define: {missing}"


def test_limits_agree_between_schema_config_and_docs():
    assert SCHEMA["properties"]["findings"]["maxItems"] == CONFIG["limits"]["max_findings"]
    assert f"At most {CONFIG['limits']['max_findings']} findings" in REVIEW_MD


def test_reviewer_branches_are_skipped_but_monthly_reviews_are_not():
    skip = CONFIG["triggers"]["skip_branches"]
    assert "reviewer/" in skip
    assert not any("review/2026-10".startswith(p) for p in skip)


def test_decision_log_has_expected_columns():
    header = next(line for line in (ROOT / CONFIG["decision_log"]).read_text().splitlines()
                  if line.startswith("| ID |"))
    cols = [c.strip() for c in header.strip("|").split("|")]
    assert cols == ["ID", "Date", "Review file", "Finding", "Reviewer", "Severity", "Decision", "Reason", "Fixed in"]


TEMPLATES = REPO / "templates"


def test_fixture_uses_the_templates_unchanged():
    """The fixture project is the templates plus test data, so the tests also check what projects copy."""
    for rel in ("REVIEW.md", "review/RESPOND.md"):
        assert (ROOT / rel).read_text() == (TEMPLATES / rel).read_text(), rel
    template = yaml.safe_load((TEMPLATES / "review" / "config.yaml").read_text())
    for key in ("authors", "default_author", "default_reviewer", "reviewers", "limits", "triggers"):
        assert template[key] == CONFIG[key], key


def test_template_config_defaults_are_consistent():
    cfg = yaml.safe_load((TEMPLATES / "review" / "config.yaml").read_text())
    reviewers = cfg["reviewers"]
    for name, a in cfg["authors"].items():
        r = reviewers[a["default_reviewer"]]
        assert r["enabled"] and r["model"] != a["model"], name
    assert all(reviewers[cfg["default_reviewer"]]["model"] != a["model"] for a in cfg["authors"].values())
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "review.yml").read_text())
    assert wf[True]["workflow_call"]["inputs"]["label"]["default"] == cfg["triggers"]["pr_label"]
