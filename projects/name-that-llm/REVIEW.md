# Name That LLM milestone review

Project ID: `name-that-llm`. Follow the [manual procedure](../REVIEW.md) and
[project policy](POLICY.md). Owner-manual initiation only; no automatic or scheduled
Claude reviews. Use the shared 15-point budget gate before spending this project's
8-point allocation or owner-assigned contingency.

Select a review after a validation methodology is fixed, an offline submission pipeline
has evidence, or a material modeling decision changes. These are future milestones,
not authorization to run a baseline in this PR.

Ask Claude to check prompt-grouped validation and leakage, balanced accuracy/per-class
recall, legal/public input provenance, exact label/ID coverage, offline dependency/model
availability, and credible nine-hour runtime evidence. Distinguish interactive smoke
tests from hidden-test scoring. Supply synthetic text, not competition passages.

Bind the review to `name-that-llm`, base/head SHA and full experiment IDs. Keep sanitized
findings and owner decisions in `projects/name-that-llm/reviews/`; do not attach Squares
records, private artifacts or author chat to a fresh blind review.
