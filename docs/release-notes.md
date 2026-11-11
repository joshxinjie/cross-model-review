# Unreleased

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
