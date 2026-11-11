# cross-model-review

A model from a **different family** reviews your pull requests and your whole project, and the model that built
the work answers the findings. Built for repos where AI models write the code and a human approves every merge.

- `/review` on a PR: a reviewer from another model family posts inline comments and a summary with a verdict.
- `/respond` on a PR: the model that built it answers each finding (accept, modify, reject, defer), applies its
  fixes, and opens a fix PR into the reviewed branch. Merging it accepts the decisions; closing it rejects them.
- Project reviews by hand or on a schedule, opened as a PR you can `/respond` to.
- Every decision is logged, and reviewers read the log so they don't re-raise settled findings.

Runs on subscriptions, not API credits: Claude models through Claude Code (`claude setup-token`) and OpenAI GPT
through the Codex CLI on a ChatGPT login.

## Who reviews whom

Each PR's author is found from its branch name. The defaults (all set in your `review/config.yaml`):

| PR built by | Branch | `/review` runs | Also | `/respond` answered by |
|---|---|---|---|---|
| Claude | anything else | GPT (Codex) | another non-Claude family | Claude Opus |
| Codex | `codex/…` | Claude Opus | `/review fable` | Codex |
| Project reviews | — | GPT (Codex) | different family from `default_author` | Claude Opus |

A reviewer from the same model family as the PR's author is refused, even when model IDs or provider aliases differ. Unknown or conflicting families fail closed. Project reviews use `default_author` for this check; they are not independent of every contributor.

## Add it to a repo

The harness reads a repo's settings from its default branch, so land them in two PRs: first the settings files
(steps 1–2 below, without the workflows), then the workflows. The first PR can't be reviewed by the new setup.

1. **Copy the templates** into the repo, keeping their paths:
   - `templates/workflows/review.yml` and `respond.yml` → `.github/workflows/`
   - `templates/review/config.yaml` and `templates/review/RESPOND.md` → `review/`
   - `templates/REVIEW.md` → `REVIEW.md`, then fill in its two "fill in" sections (the project's goal and its
     own checks)
   - `templates/reviews/decisions.md` → `reviews/`
2. **Adjust `review/config.yaml`**: `context` (which files every review reads, which areas a project review covers,
   what to leave out), `footer`, extra `protected` paths, `schedules`, `agent_env` (plain settings the tests need,
   never credentials), and `triggers.review_on_open` to review every PR when it opens (then add `opened`,
   `reopened`, `ready_for_review` to the caller's `pull_request` types; drafts wait until marked ready).
   `scopes` limits what the author may change when answering reviews of PRs on some branches.
   `generated_paths` lists files your own automation commits to PRs (e.g. backtest results): commits touching only
   those don't make a review stale, so `/respond` can still answer it.
3. **Adjust the caller workflows**: the `install` command (e.g. `pip install -e ".[dev]"`) so reviewers can run your
   tests, the `label`, and `check` in `respond.yml`: a command run after the author's changes (tests, a PR guard)
   whose result goes in the fix PR, because checks on a PR the workflow opens with its own token may not start, or
   may wait for your approval. The fix PR opens as a normal PR only when `check` exits 0; a failed check, no `check`,
   or a check that did not finish opens a draft with the reason first. The author also reports, per finding, how it
   verified the fix (`ran`, `read`, `none`) and the outcome; anything not shown to pass is listed as a verification
   gap.
4. **Repo settings → Actions → General**: allow GitHub Actions to create pull requests (project reviews and fix
   PRs are pull requests).
5. **Secrets** (repo → Settings → Secrets and variables → Actions):
   - `CLAUDE_CODE_OAUTH_TOKEN`: from `claude setup-token`.
   - `CODEX_AUTH_JSON`: for GPT reviews and Codex answers. On a computer, put `cli_auth_credentials_store = "file"`
     in `~/.codex/config.toml`, run `codex login`, save `~/.codex/auth.json` as the secret, then delete the local
     file (`rm`, not `codex logout`, which would revoke it). **Use a separate login per repo**: two repos sharing
     one would invalidate each other's refresh token.
   - `SECRETS_WRITE_TOKEN`: a fine-grained token for this repo only with "Secrets: Read and write". Codex renews
     its login about every 8 days and the workflow saves it back with this.
6. If AI models build in the repo with Codex, add an `AGENTS.md` telling them the repo's rules and to use `codex/`
   branches.

## How a run keeps the review honest

- **Three folders.** The harness (this repo, at the ref the caller pins), the project's `main` (config, instructions,
  decision log) and the PR's head (left exactly as pushed) are separate checkouts. A PR cannot change how it is
  reviewed, and the reviewer reads and tests one revision.
- **No GitHub token near a model.** The review and answer steps get no GitHub token and the git credential is removed
  before any PR code runs (including `install`); only the steps that post or push get one back.
- **Sandboxes.** Claude Code reviewers have read-only tools plus a short list of commands; Codex reviewers work in a
  throwaway copy with the network off and cached web search only. Authors can edit the PR's files but never the
  review machinery (`REVIEW.md`, `review/`, `reviews/`, `.github/`, plus `protected`), and cannot commit or push.
- **Validation.** Answers are checked against a JSON schema; a malformed answer gets one retry, inside one time
  budget per run.
- **One queue per login.** Runs that use the ChatGPT login wait for each other, across both workflows.

## Closing reviews (opt in)

Review rounds cost the most. A project can set `limits.full_reviews: N` in `review/config.yaml`, and describe the rule
in its REVIEW.md. A PR's first N reviews are then full reviews. From review N+1 on, the reviewer is told it is a
*closing review*: it checks the fixes made since the earlier reviews, what they touch, regressions, and every earlier
finding still open; in code the fixes did not change it reports only new `critical` and `major` findings and
questions needed for correctness. The posted summary says open findings are the owner's to decide: no further
`/respond` or review runs unless asked. `/review full` asks for a full review whatever the count (the reviewer still
sees the decision log, so it is not a blind review). Reviews are counted from `reviewer/archive`: valid, completed
reviews of that PR, across dates and reviewers, `/review force` repeats included; responses, project reviews and
failed or invalid runs are not. If the archive can't be read, the review is a full one. Without the setting, nothing
changes.

## Pinning

Pin each project to a reviewed commit of this repo: the same full 40-character SHA in `uses: …@<sha>` and in
`harness-ref: <sha>`, as the templates do. A tag or branch can move (`@main` picks up every change here the moment it
merges), so it is at most a readable label in a comment next to the SHA. Update a project by changing both SHAs in its
own pull request; roll back the same way. A project still on `@main` gets every merged change at its next run, so
changes here say which behaviour they alter, and are announced before they merge.

Within a run, both jobs use the same harness commit (the gate resolves the ref once), and every review and response
record stores it as `harness`, so a result can always be traced to the code that produced it.

## Actions minutes

`python -m review_harness.minutes --repo owner/name --since YYYY-MM-DD` reports a repo's GitHub Actions use per
workflow and job, from the jobs API (every run attempt, every page, each job once). It keeps apart what it measures
(job run time from start and end times), what it estimates (each job rounded up to a whole minute, as GitHub bills
hosted runners) and what it cannot see: jobs without timestamps are counted, not guessed, and model provider costs
(subscriptions, API credits) are not Actions minutes and are not included. `--allowance-user <login>` adds the
account's included minutes and usage when the billing API returns them; otherwise it says they are unavailable.
Needs `GITHUB_TOKEN` (or `GH_TOKEN`) with read access to Actions.

## Develop

```
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests run the harness against `tests/fixture`, a small project made from the templates. No API calls.

## Project collaboration

For GPT–Claude coordination beyond individual reviews, see the proposed
[collaboration charter](docs/collaboration/CHARTER.md),
[project adoption record](docs/collaboration/PROJECT_TEMPLATE.md) and
[handoff template](docs/collaboration/HANDOFF_TEMPLATE.md).
These documents do not change the harness, grant permissions or automatically adopt new project schedules.

The [Kaggle project foundations](projects/README.md) define separate policy, configuration,
experiment contracts and manual milestone review procedures for Name That LLM and Squares
in Squares. They are declarative records only; existing consumers and review/response
workflows are unchanged.

## Manual Kaggle reviews

The offline [manual packet CLI](docs/manual-review.md) exports explicitly selected, bounded
project snapshots and validates manually supplied findings. It never invokes a model,
posts to GitHub or participates in `/review`, `/respond` or `reviewer/archive`.

Before updating an existing consumer's harness pin, read the
[cross-family migration notes](docs/release-notes.md#cross-family-review-migration).
Old `default_author: claude` / `default_reviewer: fable` configurations now skip project
reviews. Change `review/config.yaml`'s `default_reviewer` (and per-author defaults where
needed) and configure the selected subscription credential; GPT needs `CODEX_AUTH_JSON`.
There is no automatic provider or billing fallback. `/respond` is unaffected.
