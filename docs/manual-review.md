# Offline manual review packets

`python -m review_harness.manual` exports a bounded packet and imports structured findings
for `name-that-llm` or `squares-in-squares`. It never imports a provider, invokes a model,
contacts Kaggle/GitHub, installs dependencies, executes reviewed code, commits or pushes.
Run it in an owner-controlled cloud shell with the existing Python development dependencies.
No API keys, subscription credentials or model-triggering workflows are needed.

This implements transport only. The [shared project policy](../projects/POLICY.md) still
requires owner-started Claude Max milestone reviews, no automatic/scheduled invocation,
no paid APIs/extra usage/fallbacks, and a combined maximum of 15 percentage points of total
weekly allowance with 70 reserved for existing usage. The CLI neither checks nor spends
that allowance. The owner must apply the budget/access gate before starting Claude.

## Export

Use a clean committed harness checkout containing this CLI and a clean tracked target
checkout at the exact head under review. `--repo` must name the target repository root.
Its `origin` must identify the same GitHub `owner/name` as `--repository`; HTTPS and SSH
GitHub origins are supported, credentialed URLs are rejected. Base must be an ancestor
of head. Only full lowercase 40-character commit SHAs are accepted, not branches/tags.

```sh
python -m review_harness.manual export \
  --repo /cloud/cross-model-review \
  --project name-that-llm \
  --repository joshxinjie/cross-model-review \
  --base <full-base-sha> --head <full-head-sha> \
  --author-model gpt-6.1-sol --reviewer-model claude-opus-5-5 \
  --file projects/name-that-llm/README.md \
  --out /tmp/manual-review-packet.json \
  --confirm-sanitized
```

Replace angle-bracket placeholders before running. Model IDs here illustrate recorded
identities, not an availability check. The owner supplies the real author/reviewer models.
The reviewer must be a recognized Claude family model and different from the author family.
The author model is used for the guard but is not included in the exported context.

Repeat `--file` for up to 16 unique explicitly selected project files. No globbing,
dependent-file discovery, PR bodies, commit messages, author chats, review archives,
decision logs or other project's files are automatically collected. Only committed
regular blobs with `.py`, `.md`, `.yaml`, `.yml`, `.json` or `.toml` suffixes are accepted.
Private/data/artifact/output/model/submission/history paths and sensitive filenames are
blocked. Symlinks, submodules, binaries, notebooks with outputs and deleted head files
are unsupported. New files are supported. Both base and head content are checked; removed
secrets in a diff cannot escape the content checks. Untracked files are never evidence.

The packet contains pinned shared/project review policies from the harness commit,
selected head files, their two-endpoint base-to-head diffs, file hashes and the expected
response JSON schema. It reuses context `Item`, `render`, `sanitize` and token estimation,
plus the existing review schema and validators. It intentionally does not use the normal
history-aware full context builders or their automatic dependent discovery. A byte bound
is enforced **without truncation or silently dropped files**: 64,000 bytes by default,
`--max-bytes` at most 128,000, and 32,000 bytes per source/evidence file or per-file diff.
The token estimate is informational, not a subscription usage estimate.

Optional completed experiment evidence:

```sh
# Add to the export command only when this sanitized, committed record exists:
--experiment projects/name-that-llm/experiments/run-1.yaml
```

Experiment IDs must match `<project-id>/<record-filename-without-yaml>`. The existing
experiment schema, project/input/notebook/artifact namespace relationships, completed
status, non-placeholder metadata, source ancestry and configuration content hash are
checked. Raw record SHA-256 and experiment ID are bound into the packet. The sanitized
manifest is included; artifact contents and private location maps are never loaded.
Input/artifact hashes and reported measurements are recorded claims, not remotely verified.
YAML anchors, aliases and duplicate keys are rejected. Examples/planned records cannot
serve as completed evidence.

The CLI prints the packet ID (SHA-256 of canonical packet payload). A private receipt is
stored under the target's Git metadata directory, `manual-review/<packet-id>.json`, mode
0600 inside a 0700 directory. Export files are 0600 and must be outside the target/harness
and any detected Git worktree. Existing files are never overwritten. Re-exporting the
same packet is refused; retain the original receipt and exported file.

Inspect the entire packet before supplying it manually to a fresh Claude Max cloud
session. `--confirm-sanitized` is an owner attestation that selected content is permitted,
sanitized and free of previous review findings. Filename filters and credential patterns
are defense in depth, **not general dataset/secret detection**. Do not upload competition
passages, datasets, private predictions/models/checkpoints, raw logs, signed links or
credentials. Disguised data, novel credentials or prior findings inside an ordinary source
file cannot be reliably identified by this CLI. Narrow the selection when uncertain.

## Import

Ask Claude to return only a JSON object with exactly `packet_id`, `binding`, and `review`.
Copy the ID and the entire binding from the packet unchanged. `review` follows the
packet's `response_schema.properties.review` (the existing `review.json` schema): scope
`pr`, at most 15 findings, unique finding IDs, schema version 1 and a verdict consistent
with severity. No prose wrapper, Markdown fence, transcript, usage metadata or extra fields.
An empty-finding review still needs an honest summary; do not treat a schema example as
an actual reviewer answer.

Before import, the owner reviews and sanitizes the structured answer in an external
private cloud file. Keep the raw response/transcript outside GitHub and worktrees.

```sh
python -m review_harness.manual import \
  --repo /cloud/cross-model-review --project name-that-llm \
  --packet-id <packet-id-printed-by-export> \
  --result /tmp/manual-review-result.json \
  --confirm-sanitized
```

The importer uses its private export receipt, **not a supplied packet**, as the authority.
It requires exact binding equality: project, repository, base/head SHA, harness SHA,
transport/review schema versions, review-schema hash, selected file hashes, experiment
IDs/hashes, expected reviewer model/family and `fresh-history-free` mode. It rechecks
current checkout HEAD, clean tracked state, origin, harness revision and evidence hashes.
A changed target or harness requires a new export. Findings can refer only to supplied
head files and in-range lines; references to earlier decisions are rejected. Validation
errors are rejected rather than automatically retried or silently fixing the verdict.
Strict JSON rejects duplicate keys, nonfinite values, excessive nesting/node counts and
inputs over 128,000 bytes. Decoded strings are scanned as well as raw bytes; encoded
credentials and control/bidirectional formatting characters cannot bypass those checks.

On success the CLI prints the path to the normalized, schema-validated record:
`projects/<project-id>/reviews/manual/<packet-id>.json`. This contains structured findings
and binding metadata only, never the raw response/transcript or full packet context.
The owner must still inspect the record before any later commit/publication. Reviewer
identity and independence are explicitly marked unverified. An import is neither an
approval nor proof that Claude actually reviewed the packet.

These records are separate from `reviewer/archive` and the normal `reviews/` archive.
`/review`, `/respond`, decision logs, closing-review counts, posting and provider selection
never consume them. No history is appended to a later manual packet automatically.
Owner/Codex follow-up remains manual under the existing project procedure.

## Duplicate handling and recovery

Each packet can be consumed once. The importer also rejects an identical normalized
review for the same project/repository/base/head even if rewrapped for a second packet.
A filesystem lock serializes exports/imports; exclusive, non-following file creation
prevents overwrites. Private consumed/result markers and the project archive are checked.
Deleting the public archive alone does not permit replay.

The importer reserves the packet/result before writing an archive. An interrupted write
fails closed and may leave a reserved packet without a complete archive. An interrupted
export may leave a receipt without an external output. Do not automatically delete state,
retry or reconstruct an answer. The owner inspects receipt/marker/archive consistency,
retains the evidence privately and decides recovery or a new genuinely scoped review.
Back up Git metadata privately: receipts are not in commits and are not carried to a new
clone. A clone without the receipt cannot import that packet. Local markers are not a
global replay-prevention service across deliberately copied/reset state or independent
clones; no such guarantee is made.

## Threat model and security review checklist

Trust the owner, Python/harness installation, committed harness policy, local Git metadata
and filesystem. Treat source blobs, diffs, experiment manifests and all model output as
untrusted. Hashes bind content; they do not authenticate a remote model, the owner's model
labels, GitHub's latest PR head or experiment measurements. Staleness is checked against
the **local checkout**, not the live GitHub PR. The owner must refresh and verify the PR
head before export/import; the CLI does not fetch or make network requests.

- [x] Explicit two-project scope; canonical paths and fixed project namespaces.
- [x] Read committed regular blobs; reject traversal, symlinks/submodules and oversize input.
- [x] Disable Git external diff/textconv/fsmonitor execution; do not execute reviewed code.
- [x] Bound and inspect base content, head content, diff and completed experiment metadata.
- [x] Private export receipt; exact repository/revision/schema/content binding on import.
- [x] Reject malformed, stale, cross-project, duplicate and out-of-packet findings.
- [x] Independent archive and replay markers; serialize writers and fail closed on interruption.
- [x] Generic CLI errors never echo raw model output, rejected paths or credential values.
- [x] No provider import, credential setup, model invocation, billing fallback or workflow added.

This is not a sandbox for executing source or fetching evidence. Prompt injection in
source remains possible: packets label source as untrusted and direct the reviewer not
to execute/fetch, but cannot control a remote session. History-free export does not prove
the reviewer had no previous exposure. Use a fresh session, withhold author chat/previous
findings, and record any known contamination separately. A malicious local actor who can
rewrite receipts, harness code or Git metadata is outside this threat model. Hashes and
0600 files are not signatures or protection against that actor or hostile filesystem races.

## Cross-family compatibility change

`config.model_family` now infers OpenAI, Anthropic and Google families from recognized
providers and/or model prefixes. `codex`/`openai` are OpenAI; `claude-code`/`anthropic` are
Anthropic; `google`/`gemini` are Google. Conflicting identities and unknown families fail
closed. There is no arbitrary configurable family label that can bypass the guard.
Existing supported provider aliases with custom model aliases inherit the provider family.

Same-family variants (for example Claude Opus reviewing Claude-authored work, even through
a different adapter) are refused. Consumers with such configurations must select a
reviewer from another family. Caller workflows are unchanged. Existing callers pinned
to an older harness commit stay unchanged until they update their pin.

The templates now use GPT for project reviews because their `default_author` is Claude.
Project review independence is relative to that designated author, not every contributor;
no third-family reviewer is enabled. Per-author defaults remain Codex→Claude and
Claude→Codex. History-aware `/review` context, closing rounds, archive formats and
`/respond` behavior otherwise remain unchanged. The Kaggle policies still prohibit
using those automatic model paths for the manual projects.
