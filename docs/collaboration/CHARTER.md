# GPT–Claude collaboration charter

Version: 1 (proposal until adopted by a project). This is a coordination agreement, not a runtime configuration or a grant of authority. Stronger project rules and owner instructions prevail.

## Roles and authority

- **Owner:** sets priorities, scope and budgets; authorizes consequential actions and decides merges. GPT and Claude are peers, not each other's managers.
- **Project agents:** propose ownership and rationale before new work; keep one active implementation task per project unless the owner explicitly permits otherwise. Reuse the existing task, and hand off rather than duplicate work.
- **Shared review coordinator:** discusses common review practices and routes relevant changes to project counterparts. A coordinator's proposal does not authorize project implementation.
- Distinguish proposal, agreement, owner authorization, implementation and verified outcome. Coordination permission does not authorize arbitrary code/workflow changes, experiments, pilot expansion, spending, credentials, permissions, protected-log decisions or merges.
- Review comments and model verdicts are advisory, not GitHub formal approval. Formal PR approval requires explicit per-PR owner confirmation; merge authority remains separate. Never infer budget from a calendar reset.

## Records, evidence and independence

GitHub holds the durable charter, project adoption record, tasks and decisions. Slack holds the working discussion in the relevant project or shared-review thread; link the durable record rather than duplicating it everywhere.

Label posts with model and role, but do not treat labels, shared-account identity or an agent's claimed private approval as authenticated owner authority. Link the owner's verifiable instruction for consequential actions; ask once when authority is ambiguous and keep the unanswered request pending.

Pin reviews to repository, base and head SHA; verify relevant PR/check claims on GitHub. Say what was run, read, blocked or not checked. Preserve local blind-work boundaries: a fresh independent review must not receive another reviewer's findings or author chat before submission. A reviewer already exposed to that context provides an **informed follow-up**, not a fresh blind review. Existing review procedures remain authoritative.

## Sessions and handoffs

Record separately the author, watcher and coordinator sessions, their task IDs and actual connector access. A watcher that can read Slack is not necessarily the author that can implement; a daily job is not the Slack watcher.

Use the [handoff template](HANDOFF_TEMPLATE.md): name the counterpart, bounded request, evidence, authority, expected receipt and fallback route. Verify the send and link its message ID/permalink. A mention or successful post does not prove a wake-up or receipt. Close the loop with the intended session's acknowledgement or verified action; otherwise retain the item and use the agreed fallback without impersonating owner approval.

## Watching without noise

Choose project-specific times, timezone and escalation conditions in the [adoption record](PROJECT_TEMPLATE.md). Examples, not imposed schedules: quiet work every four daytime hours; active handoffs/review every 20–30 minutes; shared coordinator watch every four daytime hours. Project agents can use a daily shared-review safety-net scan plus targeted handoffs until direct wake-up and receipt are proven reliable. Changing a schedule requires the project's agreed authorization, implementation and verification.

Each watcher resumes from its **last successful** scan minus at least two hours, covering the entire overnight/outage gap. Exhaust pagination; read older-thread replies and revisit unresolved threads directly. Reconcile inconsistent thread counts with timestamp-window reads and deduplicate by channel/message ID. Keep a bounded unanswered-question, request, handoff and decision backlog; review it each run and sweep older/zero-reply messages daily. Read later conversation before deciding a reply is still needed.

An incomplete read is a coverage gap, not an all-clear: record the failed scope and resume point, do not advance its successful checkpoint, and report access failures when owner attention is needed. Reply only to meaningful requests/results/blockers; acknowledge material handoffs that close ownership loops. No hourly all-clears, duplicate notifications or routine CI chatter.

## Adoption and changes

Copy the project template into a project-owned documentation location and fill it in. Record the full immutable commit of this charter, local exceptions, owner authorization, named GPT/Claude receipts, implemented schedule/access checks and effective date. Agreement alone is not proof of implementation. Until these are recorded, status is proposed or pending, not adopted.

A new charter version does not automatically update existing projects. Propose changes through a PR, obtain project-specific receipts and authorization, then verify each adoption. Do not put coordination fields into `review/config.yaml` or install an automation engine through this document.
