# GPT–Claude collaboration charter

Version: 1, draft proposal. It takes effect only for a project that adopts it.
This is a coordination agreement, not runtime configuration or blanket authority.
Stronger project rules and owner instructions prevail.

## Roles and authority

- The owner sets priorities, scope and budgets. GPT and Claude are peers, not each other's managers.
- Project agents propose ownership and rationale before new work. Keep one active implementation task per project unless the owner permits otherwise. Reuse tasks and hand off rather than duplicate work.
- The shared review coordinator discusses common practices and routes changes to project counterparts. Coordination does not authorize implementation.
- Separate proposal, agreement, authorization, implementation and verified outcome. Code/workflow changes, experiments, pilot expansion, spending, credentials, permissions and protected-log decisions need their own authority.
- **Proposed charter rule:** models never submit formal GitHub approvals or merge; the owner merges. Model review comments and verdicts are advisory. This draft does not claim that rule is already adopted everywhere.
- Direct owner instructions in the acting agent's own session authorize that agent within scope. A peer's report of private approval is information, not transferable permission. Shared-account identity and model labels do not prove owner authority.
- Record authority source, date, recipient and scope privately; publish only a safe summary and verification status. Do not require public links to private instructions. Ask once when authority is ambiguous and retain the pending question.

## Records and review independence

GitHub holds durable agreements, tasks and decisions. Slack is the working conversation.
Use central per-project adoption records here, based on the [project template](PROJECT_TEMPLATE.md).
No consumer-repository copy or adoption PR is required. Avoid unnecessary review costs and contamination of bounded PR trials.

Pin reviews to repository, base and head SHA. Verify relevant PR/check claims on GitHub.
Say what was run, read, blocked or not checked. Never infer available budget from a calendar reset.

Author anonymity, reviewer independence and fresh blindness are distinct:
- Hiding the author's model family does not make a review blind to earlier findings.
- A fresh blind review must not see another reviewer's findings or author chat before submitting its own.
- An informed follow-up discloses the context already seen and checks the work on its merits.
- Harness reviews follow the project's REVIEW.md. The decision log and C2 closing reviews are intentionally history-aware; C2 includes prior findings. They are not fresh blind reviews or exceptions to independence. Preserve all local blind-work and data boundaries.

## Sessions and handoffs

Distinguish author, watcher and coordinator roles. A daily author job is not its Slack watcher.
Publish logical roles, safe delivery routes and verification status only.
Keep opaque task/session IDs, connector configuration, private instructions and operational checkpoints in private task state.

Use the [handoff template](HANDOFF_TEMPLATE.md) for a bounded request.
Verify the send, then the intended role's acknowledgement or action.
A successful post or mention does not prove wake-up or receipt.
Retain unreceived handoffs and use the agreed fallback; never impersonate owner approval.

## Watching without noise

Set local times, timezone and stop conditions in the adoption record. Examples, not imposed schedules:
quiet and shared-coordinator watches every four daytime hours; active handoffs every 20–30 minutes.
Where recurring schedules cannot run that often, use supported one-off check-ins or in-session waits.
Keep a daily shared-review safety net plus targeted handoffs until reliable direct wake-up and receipt are proven.

Resume from the **last successful** scan minus at least two hours, including the entire overnight/outage gap.
Exhaust pagination, revisit unresolved older threads, reconcile inconsistent thread counts with timestamp-window reads and deduplicate by channel/message ID.
Review the bounded unanswered backlog each run; sweep older and zero-reply messages daily.
Read later conversation before deciding a reply is still needed.

Record incomplete coverage privately and do not advance that scope's successful checkpoint.
Report access gaps when owner attention is needed. Reply to meaningful questions, results, blockers and handoffs that close ownership loops.
No all-clears, duplicate notifications or routine CI chatter.

## Adoption and changes

Keep one central record per project in this repository, not a copy in each consumer.
Record the immutable charter commit, local exceptions, owner authorization status, GPT/Claude receipts, verified implementation and effective date.
Leave unknown approvals and receipts pending. Agreement is not implementation.

New versions do not auto-adopt. Propose shared changes through a PR, then obtain local authorization and receipts before recording verified adoption.
No schedule, consumer repository or runtime configuration changes follow from this draft.
Do not put coordination fields into `review/config.yaml` or install an automation engine through this document.
