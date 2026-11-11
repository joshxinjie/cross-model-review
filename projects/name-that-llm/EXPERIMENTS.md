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
No experiment or notebook is implemented by this specification.
