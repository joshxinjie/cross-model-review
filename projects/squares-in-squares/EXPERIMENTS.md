# Squares in Squares experiment records

Project ID: `squares-in-squares`. Follow the shared [manifest contract](../EXPERIMENTS.md)
and [schema](../experiment.schema.json); see [synthetic example](experiment.example.yaml).
Use experiment IDs `squares-in-squares/<run-id>` and artifact IDs
`squares-in-squares/<run-id>/<name>`. Sanitized manifests belong in
`projects/squares-in-squares/experiments/`. Real checkpoints and submissions remain private.

The run configuration must record puzzle set, seeds, optimization/search budget, metric
version/hash, numerical precision and checkpoint policy. Report aggregate per-puzzle and
total scores plus geometry and serialized-output validity checks when available. Do not
publish private placements, raw logs or actual private artifact locations.
No solver or search is implemented by this specification.
