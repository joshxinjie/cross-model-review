# Unreleased

## GPT-6.2 reviewer template migration

The template's normal `gpt` reviewer now pins `gpt-6.2-sol`, retaining high reasoning
effort, Codex CLI 0.164.0, `CODEX_AUTH_JSON`, and the existing refresh, sandbox, timeout,
retry, run-count and context/output budgets. The matching test fixture follows it.
The separate `authors.codex` response model remains `gpt-6.1-sol`; historical review
metadata and attribution are unchanged. The existing model-family guard refuses both
GPT-6.2 variants on OpenAI-authored work, including through provider aliases.

### Astra activation blocker

The template reserves `gpt-astra` / `gpt-6.2-astra` with the same high effort,
subscription secret and CLI pin, but **leaves it disabled**. Its intended use is an
explicit `/review gpt-astra` for difficult work, replacing that run's normal reviewer.
It must never become an automatic escalation, failure fallback, second routine review
or extra scheduled review. Its present disabled state is enforced by the existing gate.

Astra's default Codex context is smaller than the current 400,000-token project pack
cap. The harness has only shared PR/project pack budgets (150,000/400,000), estimates
with characters/4, and supplies no reviewer-specific context window or compaction
settings. A pack also excludes system instructions, schema, tool overhead and later
retry/tool history from its estimate. Enabling Astra unchanged is therefore blocked;
do not silently truncate the pack, reduce the shared Sol budget, or set a larger CLI
window merely because the API advertises one.

Before enabling it, verify the pinned CLI's model catalog and effective context and
compaction limits for the subscription. Then add and test a reviewer-specific preflight
bound for the complete prompt, output/reasoning allowance and retry/tool history.
Oversize inputs must fail explicitly before a model call, identifying the limiting
reviewer and requesting an intentionally narrower scope. Also prevent any unrequested
context compaction from being mistaken for a complete review. If these guarantees
cannot be established, keep Astra disabled and report the blocker.

### Compatibility checked without model calls

The published npm package `@openai/codex@0.164.0` runs and its `exec --help` exposes
`-m`, `-s`, `-c`, `-C`, `--json`, `--ephemeral`, `--output-schema`, `-o`, and `--add-dir`,
as used by the adapter. The model argument is a string. Neither requested GPT-6.2 ID
appears literally in the installed binary; a remotely supplied model catalog may add
support. Help and binary inspection cannot prove account entitlement, model resolution,
accepted effort or effective context limits. No CLI upgrade or paid compatibility probe
is included. Offline tests use fake providers and do not establish live model access.

Official API model pages confirm the requested IDs and structured output support:
[GPT-6.2 Sol](https://developers.openai.com/api/docs/models/gpt-6.2-sol) and
[GPT-6.2 Astra](https://developers.openai.com/api/docs/models/gpt-6.2-astra).
These API specifications do not establish subscription CLI defaults or availability.

### Consumer rollout (separate project changes)

This changes templates, not any existing consumer's trusted-main configuration. After
this harness change is reviewed and merged, each project's owner should prepare its
own configuration PR and offline validation:

- **Dalio:** inspect its trusted-main `review/config.yaml`, reviewer/author routing,
  installed CLI pin and review ownership. Change only the normal GPT reviewer to Sol;
  retain the project's evidence, finance and publication gates and existing run cadence.
- **Trading Lab:** perform the same independent config migration under its project
  owner, preserving its test environment, scopes, budgets and publication gates.
- **Harness Notes:** inspect its own trusted-main config and ownership separately;
  keep reviewer and response-author choices distinct and retain its existing gates.

For each project, verify cross-family routing, subscription setup already present,
unchanged historical attribution, workflow compatibility and dry-run prompt sizes.
A new harness SHA alone does not change the configured reviewer model. If a harness
update is needed, change `uses:` and `harness-ref` to the same reviewed full SHA in
that project's own PR; keep it separate from unrelated migrations. Config must land
on trusted main before subsequent runs use it. Roll back by restoring that project's
prior model/config and, if changed, both harness pins. No extra review runs are needed
for rollout; observe the next ordinarily authorized run. Keep Astra disabled unless
its context blocker is resolved and the owner explicitly opts in for a particular run.
CRC uses a separate native review integration and needs its own assessment; these
harness template changes do not migrate it. No consumer or publication gate is changed
by this patch.

## Cross-family review migration

Before updating an existing consumer's harness pin, inspect its `review/config.yaml`.
Old templates set `default_author: claude` and `default_reviewer: fable`; that is now
refused because both belong to Anthropic. A new harness pin does not rewrite consumer
configuration. Both manual and scheduled project reviews will be skipped until corrected.

- Change top-level `default_reviewer` to an enabled reviewer from a different family than
  `default_author`. Updated templates choose `gpt` against their Claude default author.
- Ensure that reviewer's subscription credential and required workflow setup exist.
  GPT/Codex requires `CODEX_AUTH_JSON` and the existing token-refresh save-back setup.
  A Claude-only consumer must not switch to GPT without configuring that subscription path.
  It can instead leave project reviews disabled while planning a supported independent reviewer.
- Check `authors.<author>.default_reviewer` for each PR author. `/review fable` on
  Claude-authored work is intentionally refused; Claude Opus and Fable are one family.
- No API key, paid provider, extra usage or fallback is enabled automatically. Same-family
  refusals name the configuration keys to change. `/respond` is unaffected.
- Project review independence is relative to the configured `default_author`, not every
  contributor. Existing history-aware context/rounds are unchanged.

## Manual packet version 2

Requires a separate approved harness checkout anchored to fetched `origin/main`. JSON
context sections have explicit policy/source/diff roles. Linked worktrees share replay
state; fetched committed archives provide durable replay rejection after publication.
Outputs are atomic, re-export is recoverable, and `manual verify` checks archive integrity.
There is no global exactly-once guarantee for unpublished imports across independent clones.
See [manual review usage and threat model](manual-review.md). Version 1 packets from the
unmerged PR must be recreated rather than reinterpreted under version 2.

## Private manual transport authorization (Issue #16, Phase A)

Manual export/import now permits the two repository/project pairs committed in
`review_harness/manual-repositories.json`. The harness retains its separate checkout
and its own origin/main ancestry gate. Cross-repository bases must match the target's
fetched origin/main; same-repository behavior and version-2 archives remain compatible.
See [migration and security assumptions](manual-review.md#phase-a-private-cross-repository-migration-issue-16)
for pin updates, retained project paths and owner account prerequisites. No model
workflow, baseline migration or repository creation is included.
