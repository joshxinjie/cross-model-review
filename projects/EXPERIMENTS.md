# Experiment manifest contract, version 1

This is a specification for future records, not an experiment runner or artifact service.
Each project's `experiment.example.yaml` is synthetic and marked `planned`; it is not
evidence that a notebook, model, check or submission ran.

Use [experiment.schema.json](experiment.schema.json) for the structural contract. It uses
the subset already supported by `review_harness.validate.schema_errors`; no new validator
or dependency is introduced. The project contract tests additionally check namespace
relationships. Future runtime integration must implement equivalent semantic checks
before trusting any real records; these tests do not install runtime enforcement.

## Required information

| Field | Meaning |
|---|---|
| `schema_version`, `project_id` | Version 1 and exact project ID from `project.yaml` |
| `experiment_id` | `<project-id>/<run-id>`; immutable, unique within the project |
| `status` | `planned`, `completed`, `failed` or `blocked`; a plan is not a result |
| `source_sha` | Full 40-character Git commit SHA of the experiment code |
| `config_path`, `config_sha256` | Project-relative configuration path and its content hash |
| `seed` | Explicit nonnegative seed; document additional library seeds in the configuration |
| `inputs` | Logical ID, immutable version, content SHA-256, license and provenance for each input/model |
| `environment` | Cloud platform, pinned image and dependency lock SHA-256 |
| `notebook` | Project-qualified logical ID and immutable version; `not-run` only for plans/blocked work |
| `metric_version` | Version or content hash of the scoring implementation |
| `runtime_seconds` | Measured runtime; zero in a plan is a placeholder, not a measurement |
| `checks` | `ran`/`read`/`none`, distinct from `passed`/`failed`/`blocked`/`unknown`, and detail |
| `results` | Sanitized aggregate metrics only; never per-row predictions or passage text |
| `artifacts` | Project-qualified logical ID, SHA-256 and `private-cloud` visibility |

All ID suffixes use lowercase letters, digits, dots, underscores and hyphens; slash is
reserved for namespace separators. No absolute paths, `..`, cross-project configuration
paths, storage URLs or signed links. Config paths start with the project's `projects/<id>/`
root. Input and notebook logical IDs use `<project-id>/<name>`; artifact IDs use
`<experiment-id>/<name>`. These are logical names, not credentials or proof of access.

## Records and lifecycle

Sanitized records belong at `projects/<id>/experiments/<run-id>.yaml`. Private manifests
and artifact-location maps stay in the project's private cloud namespace. Record full
input provenance privately; publish only references whose disclosure is permitted.
No real experiment records are introduced by this PR.

Do not reuse experiment IDs or overwrite completed records. Add a new run for changed
code/configuration/input versions; identify superseded runs in the review or decision log.
A completed record needs actual input versions, notebook version, environment, runtime,
checks and artifact hashes. Sentinel values such as all-zero hashes, `synthetic` and
`not-run` are only for examples/plans and must not be presented as completed evidence.
The schema checks structure, not whether a measurement or hash is truthful.

Keep review history separately under `projects/<id>/reviews/`. Bind every review to its
project, repository, base SHA and head SHA; bind experiment evidence by full experiment ID.
A matching filename or namespace alone does not establish provenance or reviewer independence.
