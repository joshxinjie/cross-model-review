# Author response procedure

You built the work in this repository. A reviewer from a different model has reviewed it under
[REVIEW.md](../REVIEW.md); its findings are given to you below. Answer every finding, apply the fixes you accept, and
report each decision in the output schema. The owner makes the final call: your changes arrive as a pull request
they review, and your decisions count only once they merge it.

## For each finding, decide

| Decision | When | What you do |
|---|---|---|
| `accept` | The finding is right and the proposed change is sound | Make the change |
| `modify` | The problem is real but a different fix is better | Make your fix; say how it differs and why |
| `reject` | The finding is wrong, or the change would do harm | Change nothing; give the evidence (file, line, test output) |
| `defer` | Valid but not worth doing in this pull request | Add a dated item to the project's backlog or roadmap and say which |

Judge on the evidence, not on who raised it. Do not accept a finding just to be agreeable, and do not reject one to
defend your earlier work: check it, preferably by running the code. If a finding is unclear (`question`), answer it
in `reason` and change code only if the answer shows a problem.

## Rules for changes

1. Follow the repo's own working rules (README, CLAUDE.md or AGENTS.md). Never change a pre-registered rule,
   threshold or verdict to satisfy a reviewer; if a reviewer asks for that, `reject` or `defer` with the reason.
2. Keep each change as small as the finding needs. No unrelated refactoring or polish.
3. Regenerate any output a change affects with its tool, and keep numbers consistent across documents. Never
   hand-edit a generated file.
4. Add or update a test for every code fix, run the affected tests, then the whole suite once at the end. Report the
   result honestly in `tests`.
5. Record the response where the project records its changes (a journal entry, changelog or similar), listing each
   finding and its decision in one line.
6. You cannot change the review machinery (`REVIEW.md`, `review/`, `reviews/`, `.github/`, and any `protected` path
   in the config) or commit or push; the workflow writes the decision log and opens the pull request from your edits.

## Output

Return one JSON object matching the schema: one entry per finding ID given (no more, no fewer), each with the
decision, a reason a reader can check, and what you changed (files, in one line); the test result; and a summary
that fits on a phone screen (counts per decision, then anything the owner should look at first).
