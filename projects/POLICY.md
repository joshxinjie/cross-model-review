# Shared subscription-only operating policy

Applies only to `name-that-llm` and `squares-in-squares`. The machine-readable companion
is [policy.yaml](policy.yaml). Existing harness consumers keep their current behavior.

## Roles and authority

The owner sets priorities, accepts competition rules, authorizes experiments and any
publication, initiates milestone reviews, selects submissions and merges PRs.
Codex Cloud does engineering, tests, notebook preparation, result analysis and fixes.
Claude Max provides selective independent advisory reviews through an owner-started
cloud session. Keep one active implementation task per project unless the owner
explicitly authorizes more. No agent formally approves or merges PRs.

Use the existing [charter](../docs/collaboration/CHARTER.md) and
[handoff template](../docs/collaboration/HANDOFF_TEMPLATE.md); retain separate proposal,
authorization, receipt and verified-outcome states. Each project's central adoption
record pins the charter version. There are no watches, recurring schedules or automatic
handoffs for these projects; this is an explicit exception to the charter's watcher
examples. dot coordination is deferred and has no task-dispatch authority here.

## Billing and Claude budget

Use existing subscriptions only. Paid OpenAI APIs, paid Anthropic APIs, extra-usage
billing and automatic paid fallbacks are prohibited. On a limit or authentication
failure, stop and report it. Never switch credentials, providers or billing mode to
continue. Do not install subscription tokens or model-triggering Actions for these projects.

Reserve 70 percentage points of the **total weekly Claude Max allowance** for existing
usage. Both Kaggle projects together may consume at most 15 percentage points: ceilings
of 8 for Name That LLM, 4 for Squares, and 3 shared contingency. The remaining 15 points
stay unallocated. These are ceilings, not targets; unused budget need not be spent.
Only the owner can assign contingency, and it remains inside the combined 15-point cap.
Do not interpret this as 15% of the remaining 30%, or 15 points per project.

Before each review, the owner checks the actual reset window, total and applicable
model/session allowances, and existing project charges. In private account state record
the window, project ID, usage before/after, contingency assigned and review completion.
Count follow-ups, failed attempts and all other Kaggle Claude activity against the same
pool. Do not publish account screenshots, usage history or session identifiers here.
Reconcile overlapping non-project activity conservatively; do not attribute an uncertain
delta away from the Kaggle pool. Actual outside usage above 70 further reduces headroom.

Never infer capacity from the calendar, token counts, elapsed time or review count.
This repository has no authoritative Max percentage meter or per-run reservation;
time/turn limits cannot enforce a hard percentage cap. Leave a substantial margin and
defer a review if available usage or its consumption cannot be bounded consistently
with the cap. No budget or reset verification means no Claude review. An owner-started
session is not permission for unattended invocation, automatic retries or scheduled reviews.

## Privacy and publication

This repository is public. Commit policy, code permitted for publication, synthetic
examples and sanitized summaries only. Never commit competition datasets or passage
text, hidden-test content, credentials, private predictions/models/submissions, raw logs,
private account/task/session IDs, signed URLs or private artifacts. Ignore rules are a
convenience, not a substitute for checking the staged diff.

Keep real artifacts in separate access-controlled cloud namespaces. Use logical IDs in
public manifests; resolve their locations privately. Do not give Claude raw competition
data or private artifacts by default. Use synthetic cases and sanitized aggregate evidence.
Any broader access needs a specific owner decision and a rules/provider-policy check.
Rules acceptance and data licenses do not automatically authorize redistribution.
No private code/data sharing outside the registered team. If publishing competition
code, satisfy the rules' Kaggle forum/notebook sharing requirements as well as licensing.

## Reproducibility and execution

Prefer Kaggle free CPU compute; enable GPU only for work that benefits from it and after
checking the account's actual quota. The audit on 2026-11-11 read official
[notebook documentation](https://www.kaggle.com/docs/notebooks): general CPU/GPU sessions
12 hours, TPU 9 hours, saved output 20 GB. Official [GPU guidance](https://www.kaggle.com/docs/efficient-gpu-usage.md)
described 30 hours/week or sometimes more depending on demand/resources. These are dated
documentation findings, not this account's verified capacity. Competition-specific limits
take precedence. Do not purchase compute or extra usage as a fallback.

Retain source SHA, configuration, seeds, input/model versions and licenses, environment,
notebook version, metric version, runtime, checks, results and artifact hashes using the
[experiment contract](EXPERIMENTS.md). Do not rely on ephemeral `/kaggle/working` as the
only copy of results. No runner, submission automation or runtime enforcement is installed.
Refresh official rules before experiments and submissions; an old summary never overrides
the official rules. The source summaries in this PR come from the prior read-only audit;
implementing this policy does not invoke Kaggle or verify rule acceptance or eligibility.
