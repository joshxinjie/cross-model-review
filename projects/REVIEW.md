# Manual milestone review procedure

Adapted from the existing [review template](../templates/REVIEW.md),
[handoff template](../docs/collaboration/HANDOFF_TEMPLATE.md) and
[decision log template](../templates/reviews/decisions.md). This is a manual procedure;
it does not enable harness commands, schedules or model invocation. The optional
[manual transport](../docs/manual-review.md) implements bounded export and structured import only.

1. Codex finishes the bounded implementation and available checks. The owner decides
   whether a milestone warrants independent review after applying the shared budget gate.
   Routine edits do not trigger Claude. Do not send a `/review` command or add a review label
   for these projects; existing consumers' commands keep their existing behavior.
2. The owner starts a Claude Max cloud session manually. Supply one project's policy,
   repository URL, immutable base/head SHA, bounded diff, synthetic cases, sanitized test
   evidence and exact questions. Use the handoff template, including scope, authority,
   completion condition, receipt and fallback. Do not include private artifacts or the
   other project's records. A handoff or session launch is not proof of receipt/completion.
3. For a fresh blind review, exclude author chat and earlier reviewers' findings until
   Claude records its own findings. This differs from the history-aware harness template:
   do not include the decision log first and then call the review blind. For an informed
   follow-up, disclose previous context and include relevant decisions. Record which mode
   was used. Claude and Codex are different model families; hiding authorship alone does
   not establish independence. No unattended CLI path is assumed supported.
4. Use existing finding fields and severities from
   [review.json](../review_harness/schemas/review.json): evidence, file/line or document
   section, `verified_by`, confidence, proposed change and related decision where applicable.
   At most 15 findings; distinguish what was run, read, blocked or not checked. Do not
   claim tests passed from inspection alone. No model gives formal GitHub approval.
5. Keep a sanitized review record under `projects/<project-id>/reviews/`, with project ID,
   repository, base/head SHA, reviewer/model identity, review mode and experiment IDs.
   Handwritten records may use the template's date/scope/reviewer naming inside this namespace.
   The CLI instead reserves `manual/<packet-id>.json` for validated structured imports. Private session
   IDs, account usage, operational routing and raw transcripts stay outside the public repo.
   No imported review is represented as a harness-produced record in `reviewer/archive`.
6. Codex proposes `accept`, `modify`, `reject` or `defer` for each finding, with verification
   method (`ran`, `read`, `none`) and outcome (`passed`, `failed`, `blocked`, `unknown`).
   Reuse the decision table columns in `templates/reviews/decisions.md`, recording rows
   in this project's `reviews/decisions.md` only when the owner decides. Add superseding
   rows instead of rewriting past decisions. No automatic `/respond` is introduced.
7. The owner decides unresolved findings and merges. A changed head makes the review
   stale for the changed code: record the new SHA and scope of any recheck. No automatic
   retry, second opinion, review loop or new Claude session. Any major-finding follow-up
   needs a new owner initiation and budget check. If unavailable, leave the gap explicit.

Read the project's own `REVIEW.md` for milestone questions. This procedure does not claim
Claude has received it or that manual cloud access, budget measurement or Kaggle execution
has been tested. Never use APIs or extra usage to get around an unavailable subscription.
