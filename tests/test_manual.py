"""Adversarial offline transport tests against real Git snapshots; never call a provider."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from review_harness import manual as M
from review_harness.config import get_reviewer, model_family

SOURCE = Path(__file__).resolve().parents[1]
PID = "name-that-llm"
OTHER = "squares-in-squares"
PATH = f"projects/{PID}/source.py"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo):
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "synthetic fixture")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def work(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "remote", "add", "origin", "https://github.com/example/work.git")
    shutil.copytree(SOURCE / "review_harness", repo / "review_harness", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(SOURCE / "projects", repo / "projects")
    (repo / ".gitignore").write_text("__pycache__/\nprojects/*/private/\n")
    (repo / PATH).write_text("value = 1\n")
    history = repo / f"projects/{PID}/reviews/decisions.md"
    history.parent.mkdir()
    history.write_text("PRIVATE_PRIOR_FINDING_SENTINEL\n")
    (repo / f"projects/{OTHER}/source.py").write_text("OTHER_PROJECT_SENTINEL\n")
    base = commit(repo)
    (repo / PATH).write_text("value = 2\n")
    head = commit(repo)
    monkeypatch.setattr(M, "HARNESS_ROOT", repo)
    return repo, base, head, tmp_path


def export(work, **overrides):
    repo, base, head, tmp = work
    args = dict(repo=repo, pid=PID, repository="example/work", base=base, head=head,
                files=[PATH], experiments=[], out=tmp / "packet.json", author_model="gpt-6.1-sol",
                reviewer_model="claude-opus-5-5", max_bytes=64_000)
    args.update(overrides)
    packet_id = M.export_packet(**args)
    return packet_id, json.loads(Path(args["out"]).read_text())


def response(packet, findings=None):
    findings = findings or []
    return {"packet_id": packet["packet_id"], "binding": deepcopy(packet["binding"]), "review": {
        "schema_version": 1, "scope": "pr", "verdict": M.derive_verdict("pr", findings),
        "summary": "Synthetic structured review for tests.", "findings": findings}}


def finding():
    return {"id": "F1", "severity": "major", "area": "code", "title": "Synthetic finding", "file": PATH,
            "line_start": 1, "claim": "Synthetic claim", "evidence": "Synthetic evidence",
            "proposed_change": "Synthetic change", "verified_by": "read_code", "confidence": 0.8}


def import_response(work, packet_id, value):
    path = work[3] / "result.json"
    path.write_text(json.dumps(value))
    return M.import_result(work[0], PID, packet_id, path)


def test_roundtrip_reuses_schema_and_keeps_history_archive_separate(work):
    packet_id, packet = export(work)
    assert packet["binding"]["harness_sha"] == work[2]
    assert packet["binding"]["repository"] == "example/work"
    assert packet["binding"]["files"][0]["sha256"] == M.digest(b"value = 2\n")
    assert "value = 1" in packet["context"] and "value = 2" in packet["context"]
    assert "PRIVATE_PRIOR_FINDING_SENTINEL" not in json.dumps(packet)
    assert "OTHER_PROJECT_SENTINEL" not in json.dumps(packet)
    assert "history" not in packet["binding"]
    archive = import_response(work, packet_id, response(packet, [finding()]))
    saved = json.loads((work[0] / archive).read_text())
    assert saved["transport"] == "manual" and saved["binding"] == packet["binding"]
    assert saved["reviewer_identity_verified"] is False and saved["independence_verified"] is False
    assert not (work[0] / "reviews").exists()
    assert not (work[0] / "reviewer/archive").exists()
    assert (work[3] / "packet.json").stat().st_mode & 0o777 == 0o600
    assert (work[0] / archive).stat().st_mode & 0o777 == 0o600
    with pytest.raises(M.Rejected, match="Duplicate"):
        import_response(work, packet_id, response(packet))


@pytest.mark.parametrize("path", [f"projects/{OTHER}/source.py", f"projects/{PID}/../{OTHER}/source.py",
    f"projects/{PID}/reviews/decisions.md", f"projects/{PID}/private/input.py", f"projects/{PID}/data/input.py",
    f"projects/{PID}/source.csv", f"projects/{PID}/notebook.ipynb", f"projects/{PID}//source.py", "/etc/passwd"])
def test_reject_cross_project_sensitive_history_and_traversal_paths(work, path):
    with pytest.raises(M.Rejected):
        export(work, files=[path])
    assert not (work[3] / "packet.json").exists()


@pytest.mark.parametrize("content", [b"password = 'synthetic-password'\n", b"sk-ant-abcdefghijklmno\n",
    b"https://user:synthetic-password@example.invalid/\n", b"https://example.invalid/?token=synthetic\n",
    b"-----BEGIN RSA PRIVATE KEY-----\n", b"\xff\xfe", b"\x00binary", b"x" * (M.MAX_FILE + 1)])
def test_reject_secrets_binary_and_oversized_files(work, content):
    repo, base, _, tmp = work
    (repo / PATH).write_bytes(content)
    head = commit(repo)
    with pytest.raises(M.Rejected):
        export((repo, base, head, tmp))


def test_secrets_removed_in_diff_are_still_rejected(work):
    repo, _, _, tmp = work
    (repo / PATH).write_text("token = 'sk-ant-abcdefghijklmno'\n")
    base = commit(repo)
    (repo / PATH).write_text("value = 2\n")
    head = commit(repo)
    with pytest.raises(M.Rejected, match="sensitive"):
        export((repo, base, head, tmp))


@pytest.mark.parametrize("mutation", ["project_id", "repository", "base_sha", "head_sha", "harness_sha",
    "schema_version", "review_schema_sha256", "experiments", "reviewer_model", "review_mode", "files"])
def test_import_rejects_every_binding_mismatch(work, mutation):
    packet_id, packet = export(work)
    result = response(packet)
    result["binding"][mutation] = [] if mutation in {"files", "experiments"} else "wrong"
    if mutation == "experiments":
        result["binding"][mutation] = [{"experiment_id": OTHER + "/run", "sha256": "a" * 64}]
    with pytest.raises(M.Rejected, match="binding"):
        import_response(work, packet_id, result)
    assert not list((work[0] / f"projects/{PID}/reviews").glob("manual/*"))


@pytest.mark.parametrize("mutation", ["unknown-field", "outside-file", "duplicate-finding", "bad-line", "old-decision",
    "bad-verdict", "bool-version", "escaped-secret", "bad-scope", "raw-transcript", "control-char", "bidi", "signed-url"])
def test_import_rejects_malformed_or_unsafe_findings(work, mutation):
    packet_id, packet = export(work)
    result = response(packet, [finding()])
    review = result["review"]
    if mutation == "unknown-field": review["api_key"] = "synthetic-key"
    elif mutation == "outside-file": review["findings"][0]["file"] = f"projects/{OTHER}/source.py"
    elif mutation == "duplicate-finding": review["findings"] *= 2
    elif mutation == "bad-line": review["findings"][0]["line_start"] = 100
    elif mutation == "old-decision": review["findings"][0]["related_decision"] = "PR12-F1"
    elif mutation == "bad-verdict": review["verdict"] = "approve"
    elif mutation == "bool-version": review["schema_version"] = True
    elif mutation == "escaped-secret": review["summary"] = "sk-ant-abcdefghijklmno"
    elif mutation == "bad-scope": review["scope"] = "project"
    elif mutation == "control-char": review["summary"] = "synthetic\x1b[31m"
    elif mutation == "bidi": review["summary"] = "synthetic\u202e"
    elif mutation == "signed-url": review["summary"] = "https://example.invalid/?X-Goog-Signature=synthetic"
    else: result["transcript"] = "untrusted raw model transcript"
    path = work[3] / "result.json"
    path.write_text(json.dumps(result).replace("sk-ant", "\\u0073k-ant"))
    with pytest.raises(M.Rejected):
        M.import_result(work[0], PID, packet_id, path)


def test_stale_head_dirty_checkout_origin_and_harness(work, monkeypatch):
    packet_id, packet = export(work)
    repo = work[0]
    (repo / PATH).write_text("dirty\n")
    with pytest.raises(M.Rejected): import_response(work, packet_id, response(packet))
    head = commit(repo)
    with pytest.raises(M.Rejected, match="Stale"): import_response(work, packet_id, response(packet))
    git(repo, "checkout", "-q", work[2])
    git(repo, "remote", "set-url", "origin", "https://github.com/example/other.git")
    with pytest.raises(M.Rejected, match="identity"): import_response(work, packet_id, response(packet))
    git(repo, "remote", "set-url", "origin", "https://github.com/example/work.git")
    monkeypatch.setattr(M, "harness_commit", lambda: head)
    with pytest.raises(M.Rejected, match="Harness"): import_response(work, packet_id, response(packet))


def test_strict_json_size_keys_nan_and_depth(work):
    for raw in [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e9999}', b'{"x":"\\ud800"}', b'```json\n{}\n```', b'[' * 30 + b'0' + b']' * 30]:
        with pytest.raises(M.Rejected): M.strict_json(raw)
    packet_id, _ = export(work)
    path = work[3] / "result.json"
    path.write_bytes(b" " * (M.MAX_BYTES + 1))
    with pytest.raises(M.Rejected, match="bound"): M.import_result(work[0], PID, packet_id, path)


def test_output_input_symlinks_bounds_no_overwrite_and_duplicate_export(work):
    repo, _, _, tmp = work
    with pytest.raises(M.Rejected): export(work, out=repo / "packet.json")
    with pytest.raises(M.Rejected): export(work, max_bytes=20)
    link = tmp / "link.py"
    link.symlink_to("source.py")
    (repo / f"projects/{PID}/linked.py").symlink_to("source.py")
    head = commit(repo)
    with pytest.raises(M.Rejected, match="regular"): export((repo, work[1], head, tmp), files=[f"projects/{PID}/linked.py"])
    packet_id, packet = export((repo, work[1], head, tmp))
    with pytest.raises(M.Rejected, match="already exported"): export((repo, work[1], head, tmp))
    raw = tmp / "raw.json"
    raw.write_text(json.dumps(response(packet)))
    symlink = tmp / "result.json"
    symlink.symlink_to(raw)
    with pytest.raises(M.Rejected, match="Symlink"): M.import_result(repo, PID, packet_id, symlink)


def test_archive_symlink_and_duplicate_result_under_second_packet(work):
    packet_id, packet = export(work)
    import_response(work, packet_id, response(packet))
    (work[0] / f"projects/{PID}/reviews/manual/{packet_id}.json").unlink()
    with pytest.raises(M.Rejected, match="Duplicate"):
        import_response(work, packet_id, response(packet))
    second_id, second = export(work, out=work[3] / "second.json", reviewer_model="claude-sonnet-5")
    with pytest.raises(M.Rejected, match="Duplicate"):
        import_response(work, second_id, response(second))


def test_cross_project_receipt_and_receipt_tampering(work):
    packet_id, packet = export(work)
    raw = work[3] / "result.json"
    raw.write_text(json.dumps(response(packet)))
    with pytest.raises(M.Rejected, match="Cross-project"):
        M.import_result(work[0], OTHER, packet_id, raw)
    receipt = work[0] / f".git/manual-review/{packet_id}.json"
    data = json.loads(receipt.read_text())
    data["context"] += "tampered"
    receipt.write_text(json.dumps(data))
    with pytest.raises(M.Rejected, match="integrity"):
        M.import_result(work[0], PID, packet_id, raw)


@pytest.mark.parametrize("left,right", [("claude-opus-5-5", "claude-sonnet-5"),
    ("gpt-6.1-sol", "gpt-6-astra"), ("gpt-6.1-sol", "o3"), ("gemini-3.1-pro", "gemini-3.8-flash")])
def test_family_guard_rejects_variants(left, right):
    cfg = {"authors": {"a": {"provider": "custom", "model": left}}, "default_author": "a",
           "default_reviewer": "r", "reviewers": {"r": {"provider": "custom", "model": right, "enabled": True}}}
    with pytest.raises(ValueError, match="family"): get_reviewer(cfg)


@pytest.mark.parametrize("entry", [{"model": "unknown"}, {"provider": "codex", "model": "claude-opus-5"},
    {"provider": "anthropic", "model": "gpt-6-astra"}])
def test_family_guard_fails_closed_on_unknown_or_conflicting_identity(entry):
    with pytest.raises(ValueError): model_family(entry)


def test_families_use_provider_aliases_and_distinct_families_still_work():
    assert model_family({"provider": "anthropic", "model": "alias"}) == model_family({"provider": "claude-code", "model": "other"})
    assert model_family({"provider": "codex", "model": "alias"}) == "openai"
    cfg = yaml.safe_load((SOURCE / "templates/review/config.yaml").read_text())
    assert get_reviewer(cfg)["provider"] == "codex"
    assert get_reviewer(cfg, "opus", cfg["authors"]["codex"])["provider"] == "claude-code"
    with pytest.raises(ValueError): get_reviewer(cfg, "fable", cfg["authors"]["claude"])


def test_cli_roundtrip_from_committed_harness_without_credentials(work):
    repo, base, head, tmp = work
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(repo)}
    python = os.sys.executable
    common = [python, "-m", "review_harness.manual"]
    result = subprocess.run(common + ["export", "--repo", str(repo), "--project", PID, "--repository", "example/work",
        "--base", base, "--head", head, "--file", PATH, "--out", str(tmp / "packet.json"),
        "--author-model", "gpt-6.1-sol", "--reviewer-model", "claude-opus-5-5", "--confirm-sanitized"],
        cwd=tmp, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    packet = json.loads((tmp / "packet.json").read_text())
    raw = tmp / "result.json"
    raw.write_text(json.dumps(response(packet)))
    result = subprocess.run(common + ["import", "--repo", str(repo), "--project", PID,
        "--packet-id", packet["packet_id"], "--result", str(raw), "--confirm-sanitized"],
        cwd=tmp, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (repo / result.stdout.strip()).exists()
    # Invalid model output never appears in CLI diagnostics.
    raw.write_text('{"secret":"synthetic-password"}')
    result = subprocess.run(common + ["import", "--repo", str(repo), "--project", PID,
        "--packet-id", packet["packet_id"], "--result", str(raw), "--confirm-sanitized"],
        cwd=tmp, env=env, capture_output=True, text=True)
    assert result.returncode == 2 and "synthetic-password" not in result.stderr + result.stdout


def completed_experiment(work, mutate=None, text_suffix=""):
    repo, base, source_sha, tmp = work
    manifest = yaml.safe_load((repo / f"projects/{PID}/experiment.example.yaml").read_text())
    manifest.update(experiment_id=PID + "/run-1", status="completed", source_sha=source_sha,
                    config_sha256=M.digest((repo / f"projects/{PID}/project.yaml").read_bytes()),
                    runtime_seconds=1, metric_version="synthetic-metric-v1")
    manifest["inputs"][0]["sha256"] = "a" * 64
    manifest["environment"].update(image="synthetic-image-v1", dependency_lock_sha256="b" * 64)
    manifest["notebook"]["version"] = "synthetic-version-v1"
    if mutate:
        mutate(manifest)
    path = f"projects/{PID}/experiments/run-1.yaml"
    (repo / path).parent.mkdir(exist_ok=True)
    (repo / path).write_text(yaml.safe_dump(manifest, sort_keys=False) + text_suffix)
    head = commit(repo)
    return (repo, base, head, tmp), path


def test_completed_experiment_ids_and_content_hashes_roundtrip(work):
    work, path = completed_experiment(work)
    packet_id, packet = export(work, experiments=[path])
    evidence = packet["binding"]["experiments"][0]
    assert evidence == {"path": path, "experiment_id": PID + "/run-1",
                        "sha256": M.digest((work[0] / path).read_bytes())}
    assert packet["experiments"][0]["manifest"]["source_sha"] != "0" * 40
    import_response(work, packet_id, response(packet))


@pytest.mark.parametrize("mutation", ["other-id", "other-input", "other-notebook", "other-artifact", "bad-config-hash",
    "config-traversal", "not-completed", "placeholder", "bad-source", "yaml-duplicate", "yaml-alias"])
def test_reject_cross_project_or_unverifiable_experiment_evidence(work, mutation):
    def mutate(m):
        if mutation == "other-id": m["experiment_id"] = OTHER + "/run-1"
        elif mutation == "other-input": m["inputs"][0]["logical_id"] = OTHER + "/input"
        elif mutation == "other-notebook": m["notebook"]["logical_id"] = OTHER + "/notebook"
        elif mutation == "other-artifact": m["artifacts"] = [{"logical_id": PID + "/run-2/output", "sha256": "a" * 64, "visibility": "private-cloud"}]
        elif mutation == "bad-config-hash": m["config_sha256"] = "a" * 64
        elif mutation == "config-traversal": m["config_path"] = f"projects/{PID}/../{OTHER}/project.yaml"
        elif mutation == "not-completed": m["status"] = "planned"
        elif mutation == "placeholder": m["environment"]["dependency_lock_sha256"] = "0" * 64
        elif mutation == "bad-source": m["source_sha"] = "f" * 40
    suffix = "status: completed\n" if mutation == "yaml-duplicate" else "extra: &a [*a]\n" if mutation == "yaml-alias" else ""
    work, path = completed_experiment(work, mutate, suffix)
    with pytest.raises(M.Rejected): export(work, experiments=[path])


def test_archive_symlink_is_rejected_before_consumption(work):
    repo, _, _, tmp = work
    packet_id, packet = export(work)
    (repo / f"projects/{PID}/reviews/manual").symlink_to(tmp, target_is_directory=True)
    with pytest.raises(M.Rejected, match="Symlink"):
        import_response(work, packet_id, response(packet))
    assert not (repo / f".git/manual-review/used-{packet_id}").exists()
    assert not (tmp / (packet_id + ".json")).exists()


def test_state_symlink_and_existing_output_are_not_followed_or_overwritten(work):
    repo, _, _, tmp = work
    (repo / ".git/manual-review").symlink_to(tmp, target_is_directory=True)
    with pytest.raises(M.Rejected, match="Symlink"): export(work)
    (repo / ".git/manual-review").unlink()
    output = tmp / "packet.json"
    output.write_text("preserve-existing-output")
    with pytest.raises(FileExistsError): export(work)
    assert output.read_text() == "preserve-existing-output"


def test_special_files_and_other_worktree_outputs_rejected(work):
    repo, _, _, tmp = work
    fifo = tmp / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(M.Rejected, match="regular"): M.read_bounded(fifo)
    other_repo = tmp / "other"
    other_repo.mkdir()
    git(other_repo, "init", "-q")
    with pytest.raises(M.Rejected, match="another Git"): export(work, out=other_repo / "packet.json")


def test_concurrent_imports_have_one_winner_and_no_replay(work):
    from concurrent.futures import ThreadPoolExecutor
    packet_id, packet = export(work)
    raw = work[3] / "result.json"
    raw.write_text(json.dumps(response(packet)))
    def attempt(_):
        try:
            M.import_result(work[0], PID, packet_id, raw)
            return "accepted"
        except M.Rejected:
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["accepted", "rejected"]


def test_interrupted_import_fails_closed_without_partial_archive(work, monkeypatch):
    packet_id, packet = export(work)
    write_new = M.write_new
    def interrupt(path, value):
        if path.parent.name == "manual":
            raise OSError("synthetic interrupted publication")
        return write_new(path, value)
    monkeypatch.setattr(M, "write_new", interrupt)
    with pytest.raises(OSError): import_response(work, packet_id, response(packet))
    monkeypatch.setattr(M, "write_new", write_new)
    with pytest.raises(M.Rejected, match="Duplicate"):
        import_response(work, packet_id, response(packet))


def test_diff_driver_is_never_executed(work):
    repo, base, _, tmp = work
    sentinel = tmp / "driver-ran"
    (repo / ".gitattributes").write_text("*.py diff=evil\n")
    git(repo, "config", "diff.evil.command", f"touch {sentinel}")
    git(repo, "config", "diff.evil.textconv", f"touch {sentinel}")
    head = commit(repo)
    export((repo, base, head, tmp))
    assert not sentinel.exists()


def test_attribution_removal_preserves_head_line_numbers():
    text = "first\nCo-Authored-By: synthetic-author\nthird\n"
    assert M.packet_text(text) == "first\n\nthird\n"


def test_boolean_binding_version_cannot_compare_equal_to_integer(work):
    packet_id, packet = export(work)
    result = response(packet)
    result["binding"]["schema_version"] = True
    with pytest.raises(M.Rejected, match="binding"):
        import_response(work, packet_id, result)


def test_cli_requires_attestation_and_suppresses_invalid_arguments(capsys):
    with pytest.raises(SystemExit) as error:
        M.main(["export", "--project", "synthetic-private-value"])
    assert error.value.code == 2
    assert "synthetic-private-value" not in capsys.readouterr().err


def test_packet_bounds_and_duplicate_selection_fail_without_output(work):
    for overrides in [{"files": []}, {"files": [PATH, PATH]}, {"max_bytes": M.MAX_BYTES + 1},
                      {"experiments": ["duplicate", "duplicate"]}, {"base": "main"}]:
        with pytest.raises(M.Rejected):
            export(work, **overrides)
    assert not (work[3] / "packet.json").exists()


def test_json_node_count_is_bounded():
    with pytest.raises(M.Rejected):
        M.strict_json(json.dumps([0] * 10_001).encode())
