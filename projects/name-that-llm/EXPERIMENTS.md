# Name That LLM experiment records

Project ID: `name-that-llm`. Follow the shared [manifest contract](../EXPERIMENTS.md)
and [schema](../experiment.schema.json); see [synthetic example](experiment.example.yaml).
Use experiment IDs `name-that-llm/<run-id>` and artifact IDs
`name-that-llm/<run-id>/<name>`. Sanitized manifests belong in
`projects/name-that-llm/experiments/`. Real datasets, model files and submissions remain private.

The run configuration must record prompt-grouped split IDs, preprocessing, classifier
parameters, seed and pinned inputs/model versions. Report balanced accuracy and aggregate
per-class recall, validation checks and offline inference/runtime evidence when available.
Do not include passage text, labels by record, test predictions or actual private locations.
The [runner](baseline.py) now generates the shared v1 contract as JSON (also valid YAML),
with configuration/input/lock hashes, declared source and environment, source bundle or
notebook hash, measured runtime, pooled out-of-fold balanced accuracy and per-class recall.
Fold records contain row counts and hashes of sorted prompt-group lists; exact group
membership is reproducible privately from input bytes and the split algorithm. No raw
prompt IDs, passages or per-row predictions enter the manifest. Keep the immutable input
version available privately. The private submission is referenced by a logical artifact
ID and content hash, never by a storage path.

A completed manifest means the local validation/refit/output run completed. Its explicit
`kaggle-runtime: unknown` check prevents interpreting local completion as evidence of
Kaggle hidden-rerun performance. Actual package versions are recorded alongside the lock
hash; image and source SHA are provenance supplied by the caller. The notebook packager
checks its source bundle against the declared Git commit. Never invent provenance.
Review metadata strings for private locations or identifiers before publishing a manifest.
No competition experiment or predictions are committed here.
