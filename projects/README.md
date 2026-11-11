# Kaggle projects

| Project ID | Project | Configuration |
|---|---|---|
| `name-that-llm` | [Name That LLM](name-that-llm/README.md) | [project.yaml](name-that-llm/project.yaml) |
| `squares-in-squares` | [Squares in Squares](squares-in-squares/README.md) | [project.yaml](squares-in-squares/project.yaml) |

These are independent projects in the existing public repository. Their YAML files are
declarative policy records, **not harness runtime configuration**. The automatic review/response workflows do not load them. The separate
[manual packet CLI](../docs/manual-review.md) applies fixed project isolation and pinned policy snapshots.
Do not copy them into `review/config.yaml` or enable `/review` for these projects.

Read the shared [operating policy](POLICY.md), [policy configuration](policy.yaml),
[experiment contract](EXPERIMENTS.md), and each project's policy and review procedure.
The central adoption records live in [docs/collaboration/projects/](../docs/collaboration/projects/),
following the existing [project template](../docs/collaboration/PROJECT_TEMPLATE.md).
They distinguish this implementation's authorization from pending Claude receipts and
future runtime verification. This PR does not start experiments or adopt an automation engine.

## Isolation contract

- Use the exact immutable project ID everywhere. An experiment ID is
  `<project-id>/<run-id>`; a logical artifact ID is `<project-id>/<run-id>/<artifact-name>`.
- Keep configuration, experiment records and review history beneath that project's root.
  Never route by model name, PR title alone, or an unqualified run ID.
- `experiments/` and `reviews/` are reserved for sanitized public records. No real runs or
  reviews exist yet. Private inputs, results, models, submissions and logs stay in separate
  access-controlled cloud locations identified by the project's artifact namespace.
- `private/` is an ignored staging namespace, not persistent storage or access control.
  Never commit its contents or use git force-add to bypass the ignores. Cloud workspaces
  are disposable; retain private results in approved persistent cloud storage.
- Do not read or attach another project's records, inputs or artifacts. Shared code or
  evidence requires an explicit dependency/provenance record and owner authorization.
- Each task names one project. Split changes that affect both projects into a separately
  scoped shared-policy task; never infer permission to change the peer project.

The shared budget is the only pooled resource defined here. Project namespaces do not
partition a subscription account's actual usage allowance. These boundaries are policy
and static checks, not a security sandbox or implemented experiment router.

## Validation

Run `python -m pytest -q`. The project contract tests validate configuration, budget and
isolation invariants, plus synthetic manifests and rejection cases using the existing
schema validator. Tests make no model or Kaggle calls. There are no baselines, runners, dot integrations or model-triggering workflows in this layer.
Manual transport is opt-in; see its threat model and tests in `tests/test_manual.py`.
