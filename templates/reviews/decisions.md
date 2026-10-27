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
