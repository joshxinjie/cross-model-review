# Squares in Squares

Project ID: `squares-in-squares`. Status: policy/configuration foundation only; no solver,
experiment, review session or submission has been run by this project setup.

For each `n` from 1 to 1,000, place `n` non-overlapping unit squares in the smallest
axis-aligned enclosing square. Lower is better: sum `L / sqrt(n) - 1` over puzzles.
Future work must use the version-pinned official metric, certify geometry and preserve
decimal precision when serializing coordinates. No solver or baseline is included.

- [Configuration](project.yaml) defines this project's paths and dated competition facts.
- [Policy](POLICY.md) records rules, privacy and submission constraints.
- [Experiments](EXPERIMENTS.md) specifies reproducible evidence.
- [Review procedure](REVIEW.md) defines manual milestone reviews.
- [Central adoption record](../../docs/collaboration/projects/squares-in-squares.md) tracks authority and receipts.

Engineering belongs in Codex Cloud; future optimization should prefer Kaggle free CPU
compute with checkpointed runs. GPU use needs evidence of benefit and verified quota.
