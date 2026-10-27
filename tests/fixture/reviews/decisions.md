# Review decisions

Every finding from a cross-model review ([REVIEW.md](../REVIEW.md)) gets one row here once it is decided. Reviewers
read this log before reviewing and do not re-raise a rejected finding without new evidence (they cite the decision
ID in `related_decision`).

**Decision:** `accept` (fix as proposed) · `modify` (fix differently, say how) · `reject` (no change, say why) ·
`defer` (valid, not now; add it to the project's backlog and say where)

**Decided by:** the owner. `/respond` writes the author's proposed rows here in its pull request; they count as
decided once the owner merges it (or edits them first).

**IDs:** `PR<n>-F<k>` for finding F<k> of a PR's first review, `PR<n>-<round>-F<k>` for later rounds; project reviews
use `PROJ-<date>[-<round>]-F<k>`. Review files (`YYYY-MM-DD-<scope>-<reviewer>.json`) sit in this folder. Add new rows
at the top; never edit a decided row, add one that supersedes it.

| ID | Date | Review file | Finding | Reviewer | Severity | Decision | Reason | Fixed in |
|---|---|---|---|---|---|---|---|---|
| PR31-4-F6 | 2026-10-13 | [2026-10-14-pr31-fable.json](2026-10-14-pr31-fable.json) (copy of `reviewer/archive`) | F6: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-4-F5 | 2026-10-13 | [2026-10-14-pr31-fable.json](2026-10-14-pr31-fable.json) (copy of `reviewer/archive`) | F5: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-4-F4 | 2026-10-13 | [2026-10-14-pr31-fable.json](2026-10-14-pr31-fable.json) (copy of `reviewer/archive`) | F4: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-4-F3 | 2026-10-13 | [2026-10-14-pr31-fable.json](2026-10-14-pr31-fable.json) (copy of `reviewer/archive`) | F3: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-4-F2 | 2026-10-13 | [2026-10-14-pr31-fable.json](2026-10-14-pr31-fable.json) (copy of `reviewer/archive`) | F2: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-4-F1 | 2026-10-13 | [2026-10-14-pr31-fable.json](2026-10-14-pr31-fable.json) (copy of `reviewer/archive`) | F1: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-3-F5 | 2026-10-13 | [2026-10-13-pr31-fable-3.json](2026-10-13-pr31-fable-3.json) (copy of `reviewer/archive`) | F5: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-3-F4 | 2026-10-13 | [2026-10-13-pr31-fable-3.json](2026-10-13-pr31-fable-3.json) (copy of `reviewer/archive`) | F4: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-3-F3 | 2026-10-13 | [2026-10-13-pr31-fable-3.json](2026-10-13-pr31-fable-3.json) (copy of `reviewer/archive`) | F3: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-3-F2 | 2026-10-13 | [2026-10-13-pr31-fable-3.json](2026-10-13-pr31-fable-3.json) (copy of `reviewer/archive`) | F2: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-3-F1 | 2026-10-13 | [2026-10-13-pr31-fable-3.json](2026-10-13-pr31-fable-3.json) (copy of `reviewer/archive`) | F1: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-2-F5 | 2026-10-13 | [2026-10-13-pr31-fable-2.json](2026-10-13-pr31-fable-2.json) (copy of `reviewer/archive`) | F5: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-2-F4 | 2026-10-13 | [2026-10-13-pr31-fable-2.json](2026-10-13-pr31-fable-2.json) (copy of `reviewer/archive`) | F4: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-2-F3 | 2026-10-13 | [2026-10-13-pr31-fable-2.json](2026-10-13-pr31-fable-2.json) (copy of `reviewer/archive`) | F3: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-2-F2 | 2026-10-13 | [2026-10-13-pr31-fable-2.json](2026-10-13-pr31-fable-2.json) (copy of `reviewer/archive`) | F2: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-2-F1 | 2026-10-13 | [2026-10-13-pr31-fable-2.json](2026-10-13-pr31-fable-2.json) (copy of `reviewer/archive`) | F1: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F11 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F11: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F10 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F10: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F9 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F9: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F8 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F8: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F7 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F7: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F6 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F6: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F5 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F5: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F4 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F4: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F3 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F3: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F2 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F2: fixture finding | fable | minor | accept | fixture row | #31 |
| PR31-F1 | 2026-10-13 | [2026-10-13-pr31-fable.json](2026-10-13-pr31-fable.json) (copy of `reviewer/archive`) | F1: fixture finding | fable | minor | accept | fixture row | #31 |
