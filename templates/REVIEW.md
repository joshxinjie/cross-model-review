# Cross-model review procedure

A reviewer model from a **different model or provider** than the one that built the work reviews this repo and
suggests improvements. It runs on pull requests (on request) and, if configured, on a schedule. The reviewer only
suggests; the owner decides, and every change to `main` still arrives as a pull request the owner approves.

This file is the reviewer's instructions. The harness sends it, unchanged, to every reviewer model, so edit it here to
change what reviews look for. Which models review is set in [review/config.yaml](review/config.yaml); decisions on
past findings are in [reviews/decisions.md](reviews/decisions.md).

<!-- Replace the two "fill in" sections below with this project's goal and checks; keep the rest. -->

## What this project is for (fill in)

Judge every finding against the project's goal:

- **Goal:** what the project is trying to achieve, in one or two lines.
- **Constraints:** rules any change must respect (data it may use, limits, platforms).
- **What "done" or "good" looks like:** the test, metric or yardstick results are judged by.

## Independence rules

1. The reviewer is **not told which model built the work** and does not see the author's chat history.
2. The reviewer sees the repo's files, the diff (for PRs) and [reviews/decisions.md](reviews/decisions.md), nothing else
   from the author.
3. When several reviewers run on the same target, none sees another's findings before submitting its own.
4. The reviewer can comment on a PR or open a PR from a `reviewer/` branch. It cannot push to `main`, merge or
   approve.

## Scopes

| Scope | Trigger | Input | Output |
|---|---|---|---|
| `pr` | `/review [model]` comment or the review label on a pull request | The diff, the files it touches, files that import them, this file, the decision log | Inline PR comments and one summary comment with a verdict |
| `project` | By hand (Actions tab) or on a schedule | The files in `context.project` of the config, this file, the decision log | A review file and a summary, opened as a PR |

## What to check

### A. Fit to the goal
- Does the work move the project towards its goal? Does any change break a constraint above?
- Is effort going to something that cannot change an outcome? Say so, and say what would.

### B. Correctness
- Does the code do what its docs and plan say? Off-by-one errors, wrong joins, unit errors, silent error handling,
  randomness without a seed.
- Results and claims: are numbers in documents the ones the code produces? Is anything overstated?

### C. Tests
- Does a test cover the change, and would it fail if the change were wrong?
- Can the pipeline or build still run end to end, and does it fail loudly rather than produce bad output?

### D. Project-specific checks (fill in)
- The checks only this project needs (for example: no look-ahead in time-series data; pre-registered rules unchanged).

### Extra checks for `pr` scope
- Does the PR change past outputs or decisions? If so, does it say why?
- Review the diff in context, including callers and files that read its outputs, not the changed lines alone.

## How to write findings

1. **Evidence or it doesn't count.** Every finding names a file and line (or a document section) and gives the
   evidence: the code, the number, the source. Factual claims about the world need a source URL.
2. **Say how you checked** in `verified_by`: `ran_code`, `read_code`, `read_docs` or `external_source`. A finding
   checked only by reading is fine; say so and set `confidence` honestly. If you can run commands, check important
   claims by running the tests and say what you ran.
3. **Propose a concrete change** in `proposed_change`: what to edit, and how to test it. If unsure, use severity
   `question` instead.
4. **Prioritise.** At most 15 findings, most important first. Merge duplicates.
5. **Respect past decisions.** Do not re-raise a finding rejected in [reviews/decisions.md](reviews/decisions.md) unless
   you have new evidence; if you do, put the decision ID in `related_decision` and state what is new.
6. Stay out of style preferences unless they cause errors or confusion.
7. **Web search is for the outside world only.** Where your tools include web search, use it to check and cite facts
   about the world: sources, documentation, literature. Never search for this repository, its code, text or pull
   requests. Page fetching is not available. Any finding that relies on a search gives the URL in `evidence`.

### Severity

| Severity | Meaning |
|---|---|
| `critical` | A result or decision is wrong or would change; a broken pipeline; a project rule silently broken |
| `major` | A real weakness that could mislead: an untested claim, a constraint not enforced, a test that cannot fail |
| `minor` | Correct but fragile or unclear: missing edge case, weak test, inconsistent wording |
| `nit` | Small polish |
| `question` | The reviewer could not tell; the author should answer |

### Verdict

- `pr` scope: `approve` (no findings above `nit`), `approve_with_nits` (only `minor` and `nit`), or `changes_needed`
  (any `critical` or `major`).
- `project` scope: `healthy`, `attention` (any `major`) or `at_risk` (any `critical`).

The summary must fit on a phone screen: the verdict, then the top three findings in one line each.

## After the review

1. Findings are posted (inline comments for `pr`; a file `reviews/YYYY-MM-DD-<scope>-<reviewer>.json` for both). Every
   record is kept on the `reviewer/archive` branch, which is never merged; project reviews also arrive on `main`
   through their own `reviewer/` PR.
2. The author answers each finding: comment `/respond` on the PR. The model that built the work (instructions in
   [review/RESPOND.md](review/RESPOND.md)) decides accept, modify, reject or defer for each finding, applies the fixes
   it accepts, and opens a pull request into the reviewed PR's branch. Merging it accepts the decisions; closing it
   rejects them.
3. Every decision is added to [reviews/decisions.md](reviews/decisions.md).
