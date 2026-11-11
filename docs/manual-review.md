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

Use **two separate checkouts**. Launch Python from an owner-approved harness checkout,
not from the PR checkout. Its clean harness commit must already be an ancestor of its
fetched `origin/main`, and its origin must match the target repository identity. Policies,
schemas and validator code come from this trusted harness, never the PR head. A commit
being present in Git does not make it trusted. There is no bypass flag for unmerged code;
bootstrap a new transport version through human review and merge before production use.

Fetch and verify `origin/main` in both checkouts before use (the CLI never fetches).
Keep the target checkout's tracked files clean at the exact head under review. `--repo`
must name its repository root. GitHub HTTPS and SSH origins are supported; credentialed
URLs are rejected. Base must be an ancestor of head. Only full lowercase 40-character
commit SHAs are accepted, not branches/tags. Running with harness and target in the same
checkout is always refused, including when the PR changes no harness files.

```sh
cd /cloud/trusted-review-harness
PYTHONPATH=/cloud/trusted-review-harness python -m review_harness.manual export \
  --repo /cloud/competition-pr \
  --project name-that-llm \
  --repository joshxinjie/cross-model-review \
  --base <full-base-sha> --head <full-head-sha> \
  --author-model gpt-6.1-sol --reviewer-model claude-opus-5-5 \
  --file projects/name-that-llm/README.md \
  --out /tmp/manual-review-packet.json \
  --confirm-sanitized
```

Replace angle-bracket placeholders before running. Model identities are **owner-supplied,
self-attested labels**, not authentication or an availability check. The bare author
model string has no provider identity to cross-check. The reviewer must be a recognized
Claude family and different from the author's declared family. The author model is used
for the guard but is not included in the exported context. Unknown names fail closed.

Repeat `--file` for up to 16 unique explicitly selected project files. No globbing,
dependent-file discovery, PR bodies, commit messages, author chats, review archives,
decision logs or other project's files are automatically collected. Only committed
regular blobs with `.py`, `.md`, `.yaml`, `.yml`, `.json` or `.toml` suffixes are accepted.
Private/data/artifact/output/model/submission/history paths and sensitive filenames are
blocked. Symlinks, submodules, binaries, notebooks with outputs and deleted head files
are unsupported. New files are supported. Both base and head content are checked; removed
secrets in a diff cannot escape the content checks. Untracked files are never evidence.

The version-2 packet contains pinned shared/project review policies from the trusted harness commit,
selected head files, their two-endpoint base-to-head diffs, file hashes and the expected
response JSON schema. Context is a JSON array of `{path, role, text}` sections, with explicit `policy`, `source`
and `diff` roles. Source text containing fake delimiter headings remains source data, not
a new policy section. It reuses context attribution sanitization and token estimation,
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
manifest is included as explicitly untrusted experiment evidence; artifact contents and private location maps are never loaded.
Input/artifact hashes and reported measurements are recorded claims, not remotely verified.
YAML anchors, aliases and duplicate keys are rejected. Examples/planned records cannot
serve as completed evidence.

The CLI prints the deterministic packet ID (SHA-256 of canonical packet payload). A private receipt is
stored under the target's **common** Git metadata directory (`git rev-parse --git-common-dir`),
`manual-review/<packet-id>.json`, mode
0600 inside a 0700 directory. Export files are 0600 and must be outside the target/harness
and any detected Git worktree. Existing files are never overwritten. If an identical receipt already exists, re-export
can write the packet to a new external output. An already locally consumed packet cannot be re-exported. Existing/missing-directory output failures
do not poison the packet: retry with a usable new output path. Different receipt content
is rejected. Final files are published atomically from a same-directory temporary file
using an exclusive hard link, with file and directory fsync; partial JSON never occupies
the final name. Linked worktrees share the same receipts, lock and consumption markers.

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
PYTHONPATH=/cloud/trusted-review-harness python -m review_harness.manual import \
  --repo /cloud/competition-pr --project name-that-llm \
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
credentials and control, bidi and zero-width characters (U+200B–U+200F and U+FEFF included) cannot bypass
those checks. The same format-character check applies at export.

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

## Replay guarantees, verification and cloud handoffs

Local import is once per packet within a **common Git directory**, including all linked
worktrees. Private consumed/result markers and the project archive are checked under a
shared filesystem lock. Deleting a working-tree archive alone does not permit local replay.
`result_id` includes `packet_id` and the complete binding, so identical legitimate answers
to different file selections or reviewer packets do not falsely collide.

Durable rejection uses committed records in both the target's **fetched `origin/main`**
and `HEAD`, not just the working tree. Export and import refuse packets already recorded
there, even when the target is checked out at the older reviewed head where the archive
does not exist. Archive filenames, project IDs, schemas and recomputed result IDs are
validated; duplicate IDs and changed published records fail closed. Contract tests also
parse checked-in records and reject malformed, misnamed or duplicate IDs.

This is **not global exactly-once consumption**. Independent clones with stale refs or
imports not yet committed/published cannot coordinate private state without a durable
shared service. The owner must fetch before use, publish/reconcile accepted records via
normal human-reviewed PRs, and resolve concurrent imports before merge. The contract
prevents duplicate persisted records; it cannot recover knowledge of an unpublished import
lost when a cloud container is reclaimed. No network or orchestration service is added.

For a new cloud session, recreate the trusted harness at the original `binding.harness_sha`
(still an ancestor of fetched main), check out the original target head, and repeat the
export arguments from the binding: files, experiments, reviewer and exact revisions.
Use the actual author label and a fresh output path. Deterministic reconstruction restores
the same receipt/packet ID; verify the ID matches before importing. It is allowed only
when no matching archive exists in fetched committed state. No private metadata backup
inside an ephemeral container is assumed durable. This recovery can also recreate an
unpublished packet previously consumed in a lost clone, which is why the publication and
reconciliation requirement is essential.

Inspect archives before committing or during recovery:

```sh
PYTHONPATH=/cloud/trusted-review-harness python -m review_harness.manual verify \
  --repo /cloud/competition-pr
```

This checks both projects' working-tree records and committed snapshots, parses JSON,
validates binding/schema, recomputes `result_id`, and rejects duplicates or modifications
to published records. It makes no model/network calls and needs no private receipt.
Transport version 1 packets/records from the unmerged PR are not accepted as version 2;
re-export after installing the reviewed version. There are no production records to migrate
in this repository at this change.

The importer reserves a packet/result before atomic archive publication. An interruption
may leave a consumed marker without a final record, but never truncated JSON at the final
archive name. Inspect state and run `verify`; do not automatically clear consumption
markers or invent a replacement answer. A complete archive may exist if a failure occurred
after the atomic link; verification distinguishes this from an absent archive. Temporary
files are not review records and must not be committed. Owner-led recovery is required.

## Threat model and security review checklist

Trust the owner, separately installed approved harness, fetched default-branch refs, local Git metadata
and filesystem. Treat source blobs, diffs, experiment manifests and all model output as
untrusted. Hashes bind content; they do not authenticate a remote model, the owner's model
labels, GitHub's latest PR head or experiment measurements. Staleness is checked against
the **local checkout**, not the live GitHub PR. The owner must refresh and verify the PR
head before export/import; the CLI does not fetch or make network requests.

- [x] Explicit two-project scope; canonical paths and fixed project namespaces.
- [x] Read committed regular blobs; reject traversal, symlinks/submodules and oversize input.
- [x] Disable Git external diff/textconv/fsmonitor execution; do not execute reviewed code.
- [x] Bound and inspect base content, head content, diff and completed experiment metadata.
- [x] Trusted harness ancestry and separate checkout; exact repository/revision/schema/content binding.
- [x] Reject malformed, stale, cross-project, duplicate and out-of-packet findings.
- [x] Common-worktree replay markers plus committed default-branch archive checks.
- [x] Atomic exclusive publication, directory fsync and independent archive verification.
- [x] Fixed safe rejection reasons identify failed checks without echoing input values.
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
providers and/or model prefixes. `codex`/`openai` providers and GPT/Codex/ChatGPT/o-series model prefixes are OpenAI; `claude-code`/`anthropic` are
Anthropic; `google`/`gemini` are Google. Conflicting identities and unknown families fail
closed. There is no arbitrary configurable family label that can bypass the guard.
Existing supported provider aliases with custom model aliases inherit the provider family.

Same-family variants (for example Claude Opus reviewing Claude-authored work, even through
a different adapter) are refused. Consumers with such configurations must select a
reviewer from another family. Caller workflows are unchanged. Existing callers pinned
to an older harness commit stay unchanged until they update their pin.

The templates now use GPT for project reviews because their `default_author` is Claude.
Project review independence is relative to that designated author, not every contributor;
no third-family reviewer is enabled. See the [migration notes](release-notes.md#cross-family-review-migration)
before updating an existing consumer pin. Per-author defaults remain Codex→Claude and
Claude→Codex. History-aware `/review` context, closing rounds, archive formats and
`/respond` behavior otherwise remain unchanged. The Kaggle policies still prohibit
using those automatic model paths for the manual projects.

The CLI targets Linux cloud shells. Parent symlinks are deliberately refused; on systems
where `/tmp` is a symlink (such as macOS), use its canonical real path. This does not
weaken the symlink check or introduce support for local-only workflows.
