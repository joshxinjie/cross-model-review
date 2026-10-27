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
| Claude | anything else | GPT (Codex) | `/review fable` | Claude Opus |
| Codex | `codex/…` | Claude Opus | `/review fable` | Codex |
| Project reviews | — | Fable | any other reviewer by name | Claude Opus |

A reviewer that is the same model as the PR's author is refused.

## Add it to a repo

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
3. **Adjust the caller workflows**: the `install` command (e.g. `pip install -e ".[dev]"`) so reviewers can run your
   tests, the `label`, and optionally `check` in `respond.yml`: a command run after the author's changes (tests, a PR
   guard) whose result goes in the fix PR, since GitHub runs no checks on PRs a workflow opens.
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

## Pinning

The templates call `@main`. To freeze a repo on a known version, use a tag or commit in both `uses: …@<ref>` and
`harness-ref: <ref>`.

## Develop

```
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests run the harness against `tests/fixture`, a small project made from the templates. No API calls.
