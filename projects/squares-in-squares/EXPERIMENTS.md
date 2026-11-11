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
The offline runner writes schema-compatible JSON manifests and sanitized run configuration
alongside ignored private checkpoints. A run is `planned` while its bounded search is
incomplete and `completed` after the configured steps finish and both serialized geometry
and the pinned official notebook accept every puzzle. Results include every puzzle and
the aggregate; checks record precision, completed steps, CPU budget/accounting, interval
side bounds and official reasons. Config includes puzzle set, seed, total step budget,
algorithm/code hashes and checkpoint policy. Environment records Python/platform and
installed numerical dependency versions; requirements.lock is hashed separately.

To publish sanitized evidence, copy only `manifest.json` to `experiments/<run-id>.json`
and `run.config.json` to `experiments/<run-id>.config.json`, matching the manifest's
logical config path. Inspect both first. Artifact entries contain logical IDs and hashes,
never private paths or coordinates; preserve real checkpoints privately. Reproduction
starts from the recorded source SHA, pinned environment, exact config and official
metric export. A full run and split resumes at the same completed step reproduce
placements and scores; elapsed times and checkpoint hashes (which include CPU accounting)
will differ. The runner emits no CSV submission. No experiment evidence is checked in
by this implementation; tests generate synthetic evidence in temporary directories.
