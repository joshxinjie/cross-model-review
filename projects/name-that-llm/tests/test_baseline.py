"""Synthetic only. Install this project's requirements before running this suite."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest
# Shared harness CI intentionally has no ML dependencies. The project CI command
# installs requirements.txt and runs every synthetic case, without skips.
np = pytest.importorskip("numpy", reason="Install name-that-llm/requirements.txt")
pd = pytest.importorskip("pandas", reason="Install name-that-llm/requirements.txt")
pytest.importorskip("sklearn", reason="Install name-that-llm/requirements.txt")
pytest.importorskip("pyarrow", reason="Install name-that-llm/requirements.txt")

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b = load("baseline")
packager = load("package_notebook")


@pytest.fixture
def config():
    value = json.loads((ROOT / "baseline.json").read_text())
    value.update(folds=3, char_max_features=1000, word_max_features=1000)
    return value


@pytest.fixture
def train(config):
    return pd.DataFrame([{"id": f"row-{group:02}-{label:02}", "prompt_id": f"prompt-{group}",
                          "text": f"Invented topic{group} style{label} style{label} conclusion {group} {label}.",
                          "model": model}
                         for group in range(6) for label, model in enumerate(config["labels"])])


@pytest.fixture
def test():
    # Numeric-looking IDs must retain leading zeros; no prompt_id required in test.
    return pd.DataFrame({"id": ["001", "002", "003", "004"],
                         "text": [f"Unseen invented subject {i} style{i}." for i in range(4)]})


def test_deterministic_grouped_validation(config, train):
    first = b.grouped_validation(train, config)
    assert first == b.grouped_validation(train.sample(frac=1, random_state=7), config)
    assert len(first["folds"]) == 3
    assert sum(f["validation_rows"] for f in first["folds"]) == len(train)
    assert set(first["per_class_recall"]) == set(config["labels"])
    assert 0 <= first["balanced_accuracy"] <= 1
    a = b.fit(config, train)
    c = b.fit(config, train)
    np.testing.assert_array_equal(a.named_steps["classifier"].coef_, c.named_steps["classifier"].coef_)


def test_vocabulary_and_idf_are_train_only(config, train):
    model = b.fit(config, train)
    word = dict(model.named_steps["features"].transformer_list)["word"]
    char = dict(model.named_steps["features"].transformer_list)["char"]
    before = word.idf_.copy()
    model.predict(["ZZZZLEAKTOKENΩΩΩ unseenvalidation"])
    assert "ZZZZLEAKTOKENΩΩΩ" not in word.vocabulary_
    assert "ΩΩ" not in char.vocabulary_
    np.testing.assert_array_equal(before, word.idf_)
    # ID and prompt metadata cannot enter the features because fit consumes text only.
    changed = train.assign(id="SECRET-ID", prompt_id="SECRET-PROMPT")
    other = b.fit(config, changed)
    np.testing.assert_array_equal(model.named_steps["classifier"].coef_, other.named_steps["classifier"].coef_)


@pytest.mark.parametrize("kind", ["id", "prompt_id", "text"])
def test_leakage_guards(train, kind):
    left, right = train.iloc[:18].copy(), train.iloc[18:36].copy()
    right.iloc[0, right.columns.get_loc(kind)] = left.iloc[0][kind]
    if kind == "text":
        right.iloc[0, right.columns.get_loc(kind)] = "  " + left.iloc[0][kind].upper() + "  "
    with pytest.raises(ValueError, match="leakage"):
        b.check_disjoint(left, right)


def test_cross_prompt_duplicates_rejected(config, train):
    train.loc[18, "text"] = train.loc[0, "text"]
    with pytest.raises(ValueError, match="leakage"):
        b.grouped_validation(train, config)


def test_missing_class_and_too_few_prompts_rejected(config, train):
    with pytest.raises(ValueError, match="classes"):
        b.grouped_validation(train[train.model != config["labels"][0]], config)
    with pytest.raises(ValueError, match="distinct prompts"):
        b.grouped_validation(train[train.prompt_id == "prompt-0"], config)
    train.loc[0, "model"] = "made-up-model"
    with pytest.raises(ValueError, match="Unknown labels"):
        b.grouped_validation(train, config)


def test_macro_recall_differs_from_accuracy(config):
    labels = config["labels"]
    truth = [labels[0]] * 100 + labels[1:]
    prediction = [labels[0]] * len(truth)
    score = b.evaluate(truth, prediction, labels)
    assert score["balanced_accuracy"] == pytest.approx(1 / 18)
    assert np.mean(np.array(truth) == prediction) > .8


@pytest.mark.parametrize("mutation", ["null", "duplicate", "missing", "extra", "unknown", "columns", "numeric"])
def test_bad_submission_rejected(config, test, mutation):
    frame = pd.DataFrame({"id": test.id, "model": config["labels"][0]})
    if mutation == "null": frame.loc[0, "model"] = None
    if mutation == "duplicate": frame.loc[0, "id"] = frame.loc[1, "id"]
    if mutation == "missing": frame = frame.iloc[1:]
    if mutation == "extra": frame.loc[0, "id"] = "unexpected"
    if mutation == "unknown": frame.loc[0, "model"] = "unknown"
    if mutation == "columns": frame["index"] = 0
    if mutation == "numeric": frame["id"] = [1, 2, 3, 4]
    with pytest.raises(ValueError):
        b.validate_submission(frame, test, config["labels"])


def metadata():
    return dict(run_id="synthetic-ci", source_sha="a" * 40, input_version="invented-v1",
                license="synthetic-test-only", provenance="Invented in test; no competition records",
                image="synthetic-ci-python-3.12", platform="codex-cloud", notebook_version="b" * 64)


def test_end_to_end_manifest_and_parquet(tmp_path, config, train, test, monkeypatch):
    # Python network attempts fail; all training/inference/packaging inputs are local.
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("Unexpected network access"))
    train.to_csv(tmp_path / "train.csv", index=False)
    test.to_csv(tmp_path / "test.csv", index=False)
    out = tmp_path / "run"
    manifest = b.run(tmp_path / "train.csv", tmp_path / "test.csv", out, config, metadata(),
                     b.digest(b.canonical(config)), b.digest((ROOT / "requirements.txt").read_bytes()),
                     "b" * 64)
    frame = pd.read_parquet(out / "submission.parquet")
    assert frame.id.tolist() == test.id.tolist()
    assert frame.columns.tolist() == ["id", "model"]
    b.validate_submission(frame, test, config["labels"])
    sys.path.insert(0, str(ROOT.parents[1]))
    from review_harness.validate import schema_errors
    schema = json.loads((ROOT.parent / "experiment.schema.json").read_text())
    assert not schema_errors(manifest, schema)
    serialized = json.dumps(manifest)
    assert str(tmp_path) not in serialized
    assert all(text not in serialized for text in train.text)
    assert "prediction" not in manifest
    assert manifest["checks"][-1]["outcome"] == "unknown"
    with pytest.raises(FileExistsError):
        b.run(tmp_path / "train.csv", tmp_path / "test.csv", out, config, metadata(), "a" * 64, "b" * 64, "c" * 64)


def test_packaged_notebook_executes_offline(tmp_path, train, test):
    notebook = packager.build_notebook("a" * 40)
    assert notebook == packager.build_notebook("a" * 40)
    assert notebook["metadata"]["name_that_llm"]["internet"] is False
    assert notebook["metadata"]["name_that_llm"]["accelerator"] == "none"
    assert all(cell.get("outputs", []) == [] for cell in notebook["cells"])
    train.to_csv(tmp_path / "train.csv", index=False)
    test.to_csv(tmp_path / "test.csv", index=False)
    # Run exact generated cells, with synthetic paths/provenance substituted in setup.
    setup = "".join(notebook["cells"][1]["source"])
    setup = setup.replace('REPLACE_WITH_IMMUTABLE_INPUT_VERSION', 'synthetic-v1').replace('REPLACE_WITH_KAGGLE_IMAGE_VERSION', 'synthetic-ci')
    setup = setup.replace("Path('/kaggle/input/competitions/name-that-llm')", f"Path({str(tmp_path)!r})")
    setup = setup.replace("Path('/kaggle/working')", f"Path({str(tmp_path / 'output')!r})")
    (tmp_path / "output").mkdir()
    script = setup + "\n" + "".join(notebook["cells"][2]["source"])
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    b.validate_submission(pd.read_parquet(tmp_path / "output/submission.parquet"), test,
                          json.loads((ROOT / "baseline.json").read_text())["labels"])


@pytest.mark.parametrize("column,value", [("id", None), ("text", " "), ("prompt_id", 3), ("model", "")])
def test_bad_training_input(train, column, value):
    train.loc[0, column] = value
    with pytest.raises(ValueError): b.check_frame(train, training=True)


def test_each_fold_fits_only_its_training_vocabulary(config, train, monkeypatch):
    original = b.fit
    seen = []
    def audited_fit(cfg, fold_train):
        model = original(cfg, fold_train)
        vocabulary = dict(model.named_steps["features"].transformer_list)["word"].vocabulary_
        excluded = set(train.prompt_id) - set(fold_train.prompt_id)
        assert excluded
        for group in excluded:
            assert f"topic{group.split('-')[-1]}" not in vocabulary
        seen.append(set(fold_train.prompt_id))
        return model
    monkeypatch.setattr(b, "fit", audited_fit)
    b.grouped_validation(train, config)
    assert len(seen) == config["folds"]


def test_class_absent_in_one_fold_rejected(config, train):
    filtered = train[(train.model != config["labels"][0]) | (train.prompt_id == "prompt-0")]
    with pytest.raises(ValueError, match="classes"):
        b.grouped_validation(filtered, config)


@pytest.mark.parametrize("update", [{"seed": -1}, {"folds": 1}, {"C": 0},
    {"word_ngram_range": [2, 1]}, {"labels": ["invented"]}, {"extra": True}])
def test_invalid_config(config, update):
    config.update(update)
    with pytest.raises(ValueError): b.build_pipeline(config)


@pytest.mark.parametrize("data", ["id,id,text\n1,2,test\n", ""])
def test_duplicate_or_empty_csv_header(tmp_path, data):
    path = tmp_path / "bad.csv"
    path.write_text(data)
    with pytest.raises(ValueError): b.read_input(path)


def test_submission_reordered_ids_are_valid(config, test):
    submission = pd.DataFrame({"id": test.id.iloc[::-1], "model": config["labels"][0]})
    b.validate_submission(submission, test, config["labels"])
