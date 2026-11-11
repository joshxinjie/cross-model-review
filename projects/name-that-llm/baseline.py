"""Offline, text-only CPU baseline. No download, provider, or submission client."""
import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import re
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import recall_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC
from threadpoolctl import threadpool_limits

PROJECT = "name-that-llm"
ROOT = Path(__file__).resolve().parent
OFFICIAL_LABELS = [
    "gpt-5.5", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-6-astra",
    "gemini-3.1-pro-preview", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash",
    "claude-fable-5", "claude-opus-4-6", "claude-opus-4-8", "claude-opus-5", "claude-sonnet-5",
    "qwen3.8-max", "glm-5.3", "glm-5.3-flash", "kimi-k3",
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def validate_config(config):
    expected = {"seed", "folds", "char_ngram_range", "word_ngram_range", "char_max_features",
                "word_max_features", "C", "max_iter", "labels"}
    if set(config) != expected:
        raise ValueError("Unexpected configuration fields")
    for key in ("seed", "folds", "char_max_features", "word_max_features", "max_iter"):
        if type(config[key]) is not int or config[key] < (0 if key == "seed" else 1):
            raise ValueError(f"Invalid {key}")
    if config["folds"] < 2 or not isinstance(config["C"], (int, float)) or not np.isfinite(config["C"]) or config["C"] <= 0:
        raise ValueError("Invalid folds or C")
    for key in ("char_ngram_range", "word_ngram_range"):
        bounds = config[key]
        if not isinstance(bounds, list) or len(bounds) != 2 or any(type(x) is not int for x in bounds) or not 1 <= bounds[0] <= bounds[1]:
            raise ValueError("Invalid n-gram range")
    if config["labels"] != OFFICIAL_LABELS:
        raise ValueError("Use the official 18 labels in canonical order")


def check_frame(frame, training=False):
    required = ["id", "text"] + (["prompt_id", "model"] if training else [])
    if not frame.columns.is_unique or not set(required) <= set(frame.columns) or frame.empty:
        raise ValueError("Missing/duplicate columns or empty input")
    for name in required:
        if not frame[name].map(lambda x: isinstance(x, str) and bool(x.strip())).all():
            raise ValueError(f"{name} must contain nonempty strings")
    if frame.id.duplicated().any():
        raise ValueError("Duplicate passage IDs")


def check_labels(values, labels, complete=False):
    observed = set(values)
    if not observed <= set(labels) or (complete and observed != set(labels)):
        raise ValueError("Unknown labels or missing required classes")


def normalized_text(values):
    # Conservative exact-duplicate audit after case/whitespace normalization.
    return {" ".join(x.casefold().split()) for x in values}


def check_disjoint(train, valid):
    if set(train.id) & set(valid.id):
        raise ValueError("Passage ID leakage")
    if "prompt_id" in valid and set(train.prompt_id) & set(valid.prompt_id):
        raise ValueError("Prompt leakage")
    if normalized_text(train.text) & normalized_text(valid.text):
        raise ValueError("Duplicate text leakage")


def build_pipeline(config):
    validate_config(config)
    common = dict(lowercase=False, sublinear_tf=True, dtype=np.float64)
    return Pipeline([
        ("features", FeatureUnion([
            ("char", TfidfVectorizer(analyzer="char", ngram_range=tuple(config["char_ngram_range"]),
                                    max_features=config["char_max_features"], **common)),
            ("word", TfidfVectorizer(analyzer="word", ngram_range=tuple(config["word_ngram_range"]),
                                    max_features=config["word_max_features"], **common)),
        ], n_jobs=1)),
        ("classifier", LinearSVC(C=config["C"], class_weight="balanced", dual=False,
                                 random_state=config["seed"], max_iter=config["max_iter"], tol=1e-4)),
    ])


def fit(config, train):
    model = build_pipeline(config)
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model.fit(train.text, train.model)
    return model


def evaluate(truth, prediction, labels):
    check_labels(truth, labels, complete=True)
    check_labels(prediction, labels)
    recall = recall_score(truth, prediction, labels=labels, average=None, zero_division=0)
    return {"balanced_accuracy": float(recall.mean()),
            "per_class_recall": dict(zip(labels, map(float, recall)))}


def grouped_validation(train, config):
    check_frame(train, training=True)
    check_labels(train.model, config["labels"], complete=True)
    # Sorting makes fold assignment independent of input row order.
    train = train.sort_values("id").reset_index(drop=True)
    if not 2 <= config["folds"] <= train.prompt_id.nunique():
        raise ValueError("Need at least folds distinct prompts and folds >= 2")
    prediction = np.empty(len(train), dtype=object)
    coverage = np.zeros(len(train), dtype=int)
    folds = []
    splitter = GroupKFold(n_splits=config["folds"])
    for number, (tr, va) in enumerate(splitter.split(train, train.model, train.prompt_id)):
        a, b = train.iloc[tr], train.iloc[va]
        check_disjoint(a, b)
        check_labels(a.model, config["labels"], complete=True)
        check_labels(b.model, config["labels"], complete=True)
        model = fit(config, a)  # Both vocabularies and IDF fitted on this fold only.
        prediction[va] = model.predict(b.text)
        coverage[va] += 1
        folds.append({"fold": number, "train_rows": len(a), "validation_rows": len(b),
                      "train_groups_sha256": digest(canonical(sorted(set(a.prompt_id)))),
                      "validation_groups_sha256": digest(canonical(sorted(set(b.prompt_id)))),
                      **evaluate(b.model, prediction[va], config["labels"])})
    if not np.all(coverage == 1):
        raise ValueError("Incomplete out-of-fold coverage")
    return {**evaluate(train.model, prediction, config["labels"]), "folds": folds}


def validate_submission(submission, test, labels):
    check_frame(test)
    if list(submission.columns) != ["id", "model"] or submission.empty:
        raise ValueError("Submission must have exactly id,model columns")
    for column in ("id", "model"):
        if not submission[column].map(lambda x: isinstance(x, str) and bool(x.strip())).all():
            raise ValueError("Submission values must be nonempty strings")
    if submission.id.duplicated().any() or len(submission) != len(test) or set(submission.id) != set(test.id):
        raise ValueError("Submission IDs must cover test exactly once")
    check_labels(submission.model, labels)


def write_submission(model, test, path, labels):
    check_frame(test)
    submission = pd.DataFrame({"id": test.id.to_numpy(), "model": model.predict(test.text)})
    validate_submission(submission, test, labels)
    path = Path(path)
    if path.name != "submission.parquet":
        raise ValueError("Output must be named submission.parquet")
    submission.to_parquet(path, index=False, engine="pyarrow")
    validate_submission(pd.read_parquet(path), test, labels)


def versions():
    return {name: importlib.metadata.version(name) for name in
            ("numpy", "scipy", "pandas", "scikit-learn", "pyarrow", "joblib", "threadpoolctl",
             "python-dateutil", "pytz", "tzdata", "six")}


def make_manifest(config, report, metadata, train_hash, test_hash, config_hash,
                  lock_hash, notebook_hash, runtime, submission_hash):
    """Only aggregate results/hashes enter the shared v1 manifest contract."""
    if metadata["platform"] not in ("kaggle", "codex-cloud"):
        raise ValueError("Unknown platform")
    for sha in (train_hash, test_hash, config_hash, lock_hash, notebook_hash, submission_hash):
        if not re.fullmatch(r"[0-9a-f]{64}", sha) or sha == "0" * 64:
            raise ValueError("Nonzero SHA-256 hashes are required")
    run = metadata["run_id"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", run):
        raise ValueError("Invalid run ID")
    if not re.fullmatch(r"[0-9a-f]{40}", metadata["source_sha"]) or metadata["source_sha"] == "0" * 40:
        raise ValueError("A real source commit SHA is required")
    for field in ("input_version", "license", "provenance", "image"):
        if not isinstance(metadata[field], str) or not metadata[field].strip():
            raise ValueError(f"Required provenance: {field}")
    checks = [
        {"name": "prompt-grouped-validation", "method": "ran", "outcome": "passed",
         "detail": json.dumps({"splitter": "GroupKFold; sorted passage IDs", "folds": report["folds"]}, sort_keys=True)},
        {"name": "leakage", "method": "ran", "outcome": "passed",
         "detail": "Disjoint prompt IDs, passage IDs and normalized exact text; fold-local TF-IDF; text-only features."},
        {"name": "submission-schema", "method": "ran", "outcome": "passed",
         "detail": "Parquet round trip: id,model; strings; unique IDs; exact test coverage; official labels."},
        {"name": "environment", "method": "read", "outcome": "passed",
         "detail": json.dumps({"python": platform.python_version(), "packages": versions()}, sort_keys=True)},
        {"name": "kaggle-runtime", "method": "none", "outcome": "unknown",
         "detail": "Local/offline execution only; nine-hour Kaggle hidden-rerun runtime remains unverified."},
    ]
    return dict(schema_version=1, project_id=PROJECT, experiment_id=f"{PROJECT}/{run}", status="completed",
                source_sha=metadata["source_sha"], config_path=f"projects/{PROJECT}/baseline.json",
                config_sha256=config_hash, seed=config["seed"],
                inputs=[dict(logical_id=f"{PROJECT}/{kind}", version=metadata["input_version"], sha256=sha,
                             license=metadata["license"], provenance=metadata["provenance"])
                        for kind, sha in (("train", train_hash), ("test", test_hash))],
                environment=dict(platform=metadata["platform"], image=metadata["image"], dependency_lock_sha256=lock_hash),
                notebook=dict(logical_id=f"{PROJECT}/baseline-notebook", version=notebook_hash),
                metric_version="macro-recall-v1", runtime_seconds=runtime, checks=checks,
                results=[dict(name="oof_balanced_accuracy", value=report["balanced_accuracy"])] +
                        [dict(name=f"oof_recall/{label}", value=value) for label, value in report["per_class_recall"].items()],
                artifacts=[dict(logical_id=f"{PROJECT}/{run}/submission", sha256=submission_hash, visibility="private-cloud")])


def read_input(path):
    # Hash exactly the bytes parsed, rather than rereading potentially changed files.
    data = Path(path).read_bytes()
    header = next(csv.reader(io.StringIO(data.decode("utf-8-sig"))), [])
    if not header or len(header) != len(set(header)):
        raise ValueError("Missing or duplicate CSV headers")
    return pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False), digest(data)


def run(train_path, test_path, output, config, metadata, config_hash, lock_hash, notebook_hash):
    validate_config(config)
    started = time.perf_counter()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    # An experiment ID/output directory is immutable, even after a partial failure.
    with (output / ".run-started").open("x") as handle:
        handle.write(metadata["run_id"])
    train, train_hash = read_input(train_path)
    test, test_hash = read_input(test_path)
    check_frame(train, training=True)
    check_frame(test)
    check_disjoint(train, test)
    report = grouped_validation(train, config)
    model = fit(config, train.sort_values("id"))
    write_submission(model, test, output / "submission.parquet", config["labels"])
    manifest = make_manifest(config, report, metadata, train_hash, test_hash,
                             config_hash, lock_hash, notebook_hash, time.perf_counter() - started,
                             digest((output / "submission.parquet").read_bytes()))
    with (output / "manifest.json").open("x") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Private, new run directory")
    parser.add_argument("--metadata", type=Path, required=True, help="Private provenance JSON; see README")
    args = parser.parse_args()
    config_bytes = (ROOT / "baseline.json").read_bytes()
    metadata = json.loads(args.metadata.read_text())
    run(args.train, args.test, args.output, json.loads(config_bytes), metadata,
        digest(config_bytes), digest((ROOT / "requirements.txt").read_bytes()),
        metadata["notebook_version"])


# CLI entry point, also used by the packaged notebook subprocess.
if __name__ == "__main__":
    main()
