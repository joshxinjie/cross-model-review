# Name That LLM CPU baseline

A deterministic, text-only classifier using character TF-IDF (2–5 grams), word
TF-IDF (1–2 grams), and a class-balanced linear SVM. Vocabulary caps bound memory;
feature extraction and numerical libraries use one worker/thread during training.
Case and punctuation are retained. No pretrained weights, external corpus, model API,
Claude call, download client or Kaggle submission client is used. Code in this directory
is covered by [MIT](LICENSE); competition data is not included or licensed by that file.

Started from main at merged PR #13 (`684dedd9a78ccbe6262b7cc9966adab57af9187e`).
The owner's 2026-11-11 request authorizes this implementation and synthetic local tests.
The older foundation-only adoption record describes the earlier scope; this work does
not verify account eligibility, rule acceptance, a real competition score, or Kaggle
runtime. Read the [official-source recheck](RULES_RECHECK.md) and [policy](POLICY.md).

## Synthetic local CI

From the repository root, with Python 3.12:

```bash
python -m venv projects/name-that-llm/.venv
projects/name-that-llm/.venv/bin/python -m pip install -r requirements-dev.txt -r projects/name-that-llm/requirements.txt
projects/name-that-llm/.venv/bin/python -m pytest -q
```

This runs the shared tests and the project synthetic suite. No datasets or credentials
are needed. The existing shared GitHub workflow installs only harness dependencies;
the project suite explicitly skips when ML dependencies are absent. To run the baseline
suite in CI, use the installation command above. Shared workflows and dependencies are
unchanged to keep this PR inside the project directory.

Tests cover all 18 official labels, deterministic coefficients and row-order-independent
CV, fold-local vocabularies/IDF, prompt/ID/normalized-text leakage, invalid inputs,
missing fold classes, imbalanced macro recall, manifests and Parquet schema/coverage.
The notebook test executes the actual packaged cells against invented CSVs in a temporary
directory. Synthetic metrics demonstrate plumbing only, not competition performance.

## Validation and reproducibility

[baseline.json](baseline.json) pins the configuration, seed and exact official labels.
Validation sorts passage IDs, uses five-fold `GroupKFold` over `prompt_id`, and fits a
fresh feature union and classifier on each training fold. Every row is evaluated once.
Each training and validation fold must contain all 18 classes; insufficient groups or
class coverage fail explicitly. Balanced accuracy is mean per-class recall across all
18 classes. The main score pools out-of-fold recalls; fold scores are also recorded.

Only `text` enters the model. IDs, prompts and labels cannot become input features.
Prompt/ID overlap and case/whitespace-normalized exact text duplicates across folds or
train/test fail rather than silently inflate the score. This is an exact-duplicate
audit, not a semantic near-duplicate detector. Prompt IDs are essential; do not invent
or infer them from test metadata. Do not hand label validation/test data.

The same pinned Python/package environment and input bytes produce deterministic
features, coefficients, splits and predictions. Runtime measurements vary. Different
BLAS/OS/library builds can change floating point results; record the actual image.
Convergence warnings fail the run. No model weights are saved.

## Private local run

Real-data execution requires the owner's separately verified rules acceptance and
appropriate cloud access. Put all input/output and provenance files under ignored
`projects/name-that-llm/private/` or another access-controlled cloud location. Never
commit competition passages, datasets, predictions, model files or credentials.

Create private metadata JSON with these fields (use real immutable versions, a committed
40-character `source_sha`, and sanitized descriptions rather than paths or account IDs):

```json
{
  "run_id": "baseline-001",
  "source_sha": "<full committed source SHA>",
  "input_version": "<immutable input version>",
  "license": "CC BY-SA 4.0; competition rules apply",
  "provenance": "Official Kaggle Name That LLM competition input",
  "platform": "codex-cloud",
  "image": "<immutable execution image version>",
  "notebook_version": "<SHA-256 of packaged source bundle or notebook>"
}
```

```bash
projects/name-that-llm/.venv/bin/python projects/name-that-llm/baseline.py \
  --train projects/name-that-llm/private/train.csv \
  --test projects/name-that-llm/private/test.csv \
  --metadata projects/name-that-llm/private/metadata.json \
  --output projects/name-that-llm/private/baseline-001
```

The runner validates, performs grouped CV, refits on all training rows, and writes only
`submission.parquet`, aggregate `manifest.json` and a run marker. A used output directory
cannot be reused, including after failure. The submission is read back and checked for
exact `id,model` columns, strings, nonnull values, valid labels, unique IDs and complete
coverage of the dynamically loaded test set. CSV IDs are read as strings to preserve
leading zeros. Test data and sample submissions never contribute features or IDF.

[Experiment records](EXPERIMENTS.md) explain the shared manifest contract. Review all
metadata before copying a sanitized manifest into `experiments/`; hashes and aggregate
metrics do not authorize publishing the underlying artifacts. No real experiment record
is included in this PR.

## Offline Kaggle packaging

Commit source changes first, then package with their actual SHA:

```bash
python projects/name-that-llm/package_notebook.py --source-sha "$(git rev-parse HEAD)" \
  --output projects/name-that-llm/build/baseline.ipynb
```

The packager verifies that the commit contains the current source/config/dependencies
and packager. It embeds code, configuration, dependency pins and license; no repository
checkout, weights, data or network connection is needed at runtime. It never uploads.
In Kaggle, personally review/accept current rules, attach the competition input, set
Internet **off**, choose accelerator **None**, and fill the notebook's input/image
provenance. Its metadata documents these settings but cannot enforce Kaggle UI settings.
The default input is `/kaggle/input/competitions/name-that-llm/`. The final file is
`/kaggle/working/submission.parquet`; keep notebook outputs private.

Preinstalled packages must match the pins. Otherwise prepare Linux x86_64 Python 3.12
wheels **before** offline execution (for another Kaggle Python version, rebuild/test the
pins and wheels for that interpreter):

```bash
projects/name-that-llm/.venv/bin/python -m pip download --only-binary=:all: \
  -r projects/name-that-llm/requirements.txt -d projects/name-that-llm/private/wheelhouse
```

Attach those wheels as a private Kaggle input and set `WHEELHOUSE` in the setup cell.
The notebook installs only from that directory using `--no-index`, starts a fresh
interpreter, and verifies pinned versions. It retrains locally on the attached training
CSV. There are no runtime downloads or API calls. Full CV plus refit is deliberate;
measure runtime/memory on the intended free CPU image before any submission. The
nine-hour hidden-rerun limit remains unverified. No submission is authorized here.

The rules require public competition code to also be shared on the competition Kaggle
forum or notebooks. The owner handles that separate publication and future participation.
[Review procedure](REVIEW.md) remains owner-manual; this task invokes no reviewer.
