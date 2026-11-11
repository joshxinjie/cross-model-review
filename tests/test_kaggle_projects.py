"""Static governance contracts only: no project router, provider or Kaggle invocation."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

import pytest
import yaml

from review_harness.validate import schema_errors

REPO = Path(__file__).resolve().parents[1]
PROJECTS = REPO / "projects"
IDS = {"name-that-llm", "squares-in-squares"}
POLICY = yaml.safe_load((PROJECTS / "policy.yaml").read_text())
SCHEMA = json.loads((PROJECTS / "experiment.schema.json").read_text())
CONFIGS = {p.parent.name: yaml.safe_load(p.read_text()) for p in PROJECTS.glob("*/project.yaml")}


def safe_relative(path):
    assert isinstance(path, str) and path and "\\" not in path
    parsed = PurePosixPath(path)
    assert not parsed.is_absolute() and ".." not in parsed.parts
    assert str(parsed) == path, f"noncanonical path: {path}"
    return parsed


def project_contract(pid, cfg):
    assert cfg["schema_version"] == 1 and cfg["project_id"] == pid
    root = PurePosixPath("projects") / pid
    expected = {
        "root": str(root), "configuration": str(root / "project.yaml"),
        "experiment_records": str(root / "experiments"), "review_history": str(root / "reviews"),
        "private_staging": str(root / "private"),
    }
    assert cfg["paths"] == expected
    for path in [*cfg["paths"].values(), *cfg["documents"].values()]:
        assert safe_relative(path).is_relative_to(root), f"outside {pid}: {path}"
    assert cfg["artifact_namespace"] == pid
    assert cfg["shared_policy"] == "projects/policy.yaml"
    assert cfg["adoption_record"] == f"docs/collaboration/projects/{pid}.md"
    assert cfg["competition"]["slug"] == pid
    assert cfg["competition"]["rules_url"] == f"https://www.kaggle.com/competitions/{pid}/rules"


def policy_contract(policy):
    assert policy["schema_version"] == 1
    assert len(policy["project_ids"]) == 2 and set(policy["project_ids"]) == IDS
    assert policy["execution"] == {
        "cloud_only": True, "preferred_compute": "kaggle-free", "engineering": "codex-cloud",
        "reviewer": "claude-max", "reviewer_initiation": "owner-manual-milestone",
        "max_active_implementation_tasks_per_project": 1, "owner_merges": True,
    }
    assert policy["billing"]["subscription_only"] is True
    for flag in ("paid_openai_api", "paid_anthropic_api", "extra_usage", "automatic_paid_fallback"):
        assert policy["billing"][flag] is False, flag
    for flag in ("automatic", "scheduled", "unattended_claude", "automatic_retry"):
        assert policy["reviews"][flag] is False, flag
    assert policy["reviews"]["require_project_and_base_head_sha"] is True
    assert policy["reviews"]["cross_model_family"] is True
    budget = policy["claude_weekly_budget"]
    assert budget["unit"] == "percentage_points_of_total_weekly_allowance"
    for value in [budget["existing_usage_reserved"], budget["combined_project_cap"],
                  budget["shared_contingency_cap"], budget["unallocated_reserve"],
                  *budget["project_caps"].values()]:
        assert type(value) is int and value >= 0
    assert budget["existing_usage_reserved"] == 70
    assert budget["combined_project_cap"] <= 15
    assert set(budget["project_caps"]) == IDS
    assert sum(budget["project_caps"].values()) + budget["shared_contingency_cap"] <= budget["combined_project_cap"]
    assert budget["existing_usage_reserved"] + budget["combined_project_cap"] + budget["unallocated_reserve"] == 100
    assert budget["accounting"] == "owner-recorded-usage-before-and-after"
    assert budget["enforcement"] == "manual-no-provider-reservation"
    assert budget["unknown_usage_action"] == "defer-review"
    assert policy["privacy"]["public_repository"] is True
    for flag in ("commit_competition_data", "commit_credentials", "commit_private_artifacts",
                 "cross_project_access_by_default"):
        assert policy["privacy"][flag] is False


def manifest_contract(pid, manifest):
    assert not schema_errors(manifest, SCHEMA), schema_errors(manifest, SCHEMA)
    assert manifest["project_id"] == pid
    experiment = manifest["experiment_id"]
    assert experiment.startswith(pid + "/")
    assert safe_relative(manifest["config_path"]).is_relative_to(PurePosixPath("projects") / pid)
    assert manifest["notebook"]["logical_id"].startswith(pid + "/")
    assert all(item["logical_id"].startswith(pid + "/") for item in manifest["inputs"])
    assert all(item["logical_id"].startswith(experiment + "/") for item in manifest["artifacts"])
    if manifest["status"] == "completed":
        assert manifest["source_sha"] != "0" * 40
        assert manifest["config_sha256"] != "0" * 64
        assert manifest["environment"]["dependency_lock_sha256"] != "0" * 64
        assert manifest["environment"]["image"] != "not-run"
        assert manifest["notebook"]["version"] != "not-run" and manifest["metric_version"] != "not-run"
        assert manifest["checks"] and manifest["runtime_seconds"] > 0
        assert all(item["sha256"] != "0" * 64 for item in manifest["inputs"] + manifest["artifacts"])


def example(pid):
    return yaml.safe_load((PROJECTS / pid / "experiment.example.yaml").read_text())


def test_two_projects_have_disjoint_canonical_namespaces_and_documents():
    assert set(CONFIGS) == IDS
    roots = []
    for pid, cfg in CONFIGS.items():
        project_contract(pid, cfg)
        roots.append(PurePosixPath(cfg["paths"]["root"]))
        for path in [cfg["adoption_record"], *cfg["documents"].values()]:
            assert (REPO / path).is_file(), path
        assert (REPO / cfg["paths"]["configuration"]).is_file()
        assert not (REPO / cfg["paths"]["root"] / "review" / "config.yaml").exists()
    assert not roots[0].is_relative_to(roots[1]) and not roots[1].is_relative_to(roots[0])


@pytest.mark.parametrize("replacement", [
    "projects/squares-in-squares/reviews", "projects/name-that-llm/../squares-in-squares/reviews",
    "/tmp/reviews", "projects/name-that-llm//reviews",
])
def test_reject_configuration_escape_or_cross_project_history(replacement):
    cfg = deepcopy(CONFIGS["name-that-llm"])
    cfg["paths"]["review_history"] = replacement
    with pytest.raises(AssertionError):
        project_contract("name-that-llm", cfg)


def test_subscription_only_shared_budget_and_owner_manual_review_policy():
    policy_contract(POLICY)


@pytest.mark.parametrize("section,flag", [
    ("billing", "paid_openai_api"), ("billing", "paid_anthropic_api"),
    ("billing", "extra_usage"), ("billing", "automatic_paid_fallback"),
    ("reviews", "automatic"), ("reviews", "scheduled"),
    ("reviews", "unattended_claude"), ("reviews", "automatic_retry"),
    ("privacy", "commit_competition_data"), ("privacy", "commit_credentials"),
    ("privacy", "commit_private_artifacts"), ("privacy", "cross_project_access_by_default"),
])
def test_reject_paid_automatic_or_privacy_policy_regressions(section, flag):
    policy = deepcopy(POLICY)
    policy[section][flag] = True
    with pytest.raises(AssertionError):
        policy_contract(policy)


@pytest.mark.parametrize("mutation", ["per-project-15", "combined-30", "remaining-percent", "unknown-continue"])
def test_reject_budget_overallocation_and_ambiguous_accounting(mutation):
    policy = deepcopy(POLICY)
    budget = policy["claude_weekly_budget"]
    if mutation == "per-project-15":
        budget["project_caps"] = dict.fromkeys(IDS, 15)
    elif mutation == "combined-30":
        budget["combined_project_cap"] = 30
    elif mutation == "remaining-percent":
        budget["unit"] = "percent_of_remaining_allowance"
    else:
        budget["unknown_usage_action"] = "continue"
    with pytest.raises(AssertionError):
        policy_contract(policy)


@pytest.mark.parametrize("pid", sorted(IDS))
def test_synthetic_examples_validate_without_claiming_execution(pid):
    manifest = example(pid)
    manifest_contract(pid, manifest)
    assert manifest["status"] == "planned"
    assert manifest["results"] == [] and manifest["artifacts"] == []
    assert manifest["checks"][0]["method"] == "none"
    # All required provenance fields must remain required, including nested fields.
    for field in SCHEMA["required"]:
        invalid = deepcopy(manifest)
        del invalid[field]
        assert schema_errors(invalid, SCHEMA), field
    for field in SCHEMA["properties"]["inputs"]["items"]["required"]:
        invalid = deepcopy(manifest)
        del invalid["inputs"][0][field]
        assert schema_errors(invalid, SCHEMA), field


@pytest.mark.parametrize("field", ["project_id", "experiment_id", "config_path", "input", "notebook", "artifact"])
def test_reject_cross_project_manifest_references(field):
    pid, other = "name-that-llm", "squares-in-squares"
    manifest = example(pid)
    if field == "project_id":
        manifest[field] = other
    elif field == "experiment_id":
        manifest[field] = other + "/synthetic-example"
    elif field == "config_path":
        manifest[field] = f"projects/{other}/project.yaml"
    elif field == "input":
        manifest["inputs"][0]["logical_id"] = other + "/input"
    elif field == "notebook":
        manifest["notebook"]["logical_id"] = other + "/notebook"
    else:
        manifest["artifacts"] = [{"logical_id": other + "/run/output", "sha256": "a" * 64,
                                  "visibility": "private-cloud"}]
    with pytest.raises(AssertionError):
        manifest_contract(pid, manifest)


@pytest.mark.parametrize("mutation", ["traversal", "wrong-run", "credential-field", "completed-placeholder", "bad-sha"])
def test_reject_invalid_or_misleading_manifest(mutation):
    pid = "name-that-llm"
    manifest = example(pid)
    if mutation == "traversal":
        manifest["config_path"] = f"projects/{pid}/../squares-in-squares/project.yaml"
    elif mutation == "wrong-run":
        manifest["artifacts"] = [{"logical_id": pid + "/different-run/output", "sha256": "a" * 64,
                                  "visibility": "private-cloud"}]
    elif mutation == "credential-field":
        manifest["notebook"]["token"] = "synthetic-secret"
    elif mutation == "completed-placeholder":
        manifest["status"] = "completed"
    else:
        manifest["source_sha"] = "main"
    with pytest.raises(AssertionError):
        manifest_contract(pid, manifest)


def test_completed_contract_accepts_synthetic_versioned_evidence():
    """Exercise the completed-state contract without claiming an actual run occurred."""
    pid = "squares-in-squares"
    manifest = example(pid)
    manifest.update(status="completed", source_sha="a" * 40, config_sha256="b" * 64,
                    metric_version="synthetic-metric-v1", runtime_seconds=1)
    manifest["inputs"][0]["sha256"] = "c" * 64
    manifest["environment"].update(image="synthetic-image-v1", dependency_lock_sha256="d" * 64)
    manifest["notebook"]["version"] = "synthetic-version-1"
    manifest["checks"] = [{"name": "synthetic-check", "method": "ran", "outcome": "passed",
                           "detail": "Invented metadata for a contract test, not execution evidence."}]
    manifest["results"] = [{"name": "synthetic-score", "value": 1.0}]
    manifest["artifacts"] = [{"logical_id": manifest["experiment_id"] + "/synthetic-output",
                              "sha256": "e" * 64, "visibility": "private-cloud"}]
    manifest_contract(pid, manifest)


def test_competition_constraints_remain_distinct():
    llm = CONFIGS["name-that-llm"]["competition"]
    squares = CONFIGS["squares-in-squares"]["competition"]
    assert (llm["max_submissions_per_day"], llm["max_final_submissions"]) == (5, 2)
    assert (squares["max_submissions_per_day"], squares["max_final_submissions"]) == (10, 1)
    assert llm["submission"] == {
        "mode": "kaggle-notebook", "filename": "submission.parquet", "columns": ["id", "model"],
        "cpu_runtime_hours_max": 9, "gpu_runtime_hours_max": 9, "internet": False,
    }
    assert squares["submission"]["mode"] == "csv"
    assert squares["submission"]["columns"] == ["id", "n", "square_id", "x", "y", "angle"]
    assert squares["submission"]["angle_unit"] == "radians"
    assert squares["submission"]["partial_puzzles"] is True
    assert squares["submission"]["notebook_execution_requirement"] == "none-found-in-audit"
    assert "internet" not in squares["submission"]
    for competition in (llm, squares):
        assert competition["rules_accepted"] is False  # no account acceptance verified by this setup
        assert competition["max_team_size"] == 5
        deadlines = [datetime.fromisoformat(competition[k].replace("Z", "+00:00"))
                     for k in ("entry_deadline_utc", "merger_deadline_utc", "final_deadline_utc")]
        assert deadlines[0] == deadlines[1] < deadlines[2]
        assert all(d.hour == 23 and d.minute == 59 and d.utcoffset().total_seconds() == 0 for d in deadlines)


def test_private_staging_is_ignored_for_both_projects():
    for pid in IDS:
        path = f"projects/{pid}/private/synthetic-checkpoint.bin"
        result = subprocess.run(["git", "check-ignore", "--no-index", path], cwd=REPO,
                                capture_output=True, text=True)
        assert result.returncode == 0 and result.stdout.strip() == path


def test_project_docs_link_locally_and_pin_existing_collaboration_sources():
    docs = list(PROJECTS.rglob("*.md")) + list((REPO / "docs/collaboration/projects").glob("*.md"))
    for doc in docs:
        for target in re.findall(r"\]\(([^)]+)\)", doc.read_text()):
            if not target.startswith("https://"):
                assert (doc.parent / target.split("#")[0]).exists(), (doc, target)
    for pid, cfg in CONFIGS.items():
        adoption = (REPO / cfg["adoption_record"]).read_text()
        assert "PROJECT_TEMPLATE.md" in adoption and "HANDOFF_TEMPLATE.md" in adoption
        assert "7c985f04d980b32e6b6c9fb5c54c0351ccbc6d1b" in adoption
        assert "Claude agreement/receipt pending" in adoption
        assert "no watches, automatic reviews or scheduled Claude reviews" in adoption
