# Name That LLM

Project ID: `name-that-llm`. Status: policy/configuration foundation only; no baseline,
experiment, review session or submission has been run by this project setup.

Identify which of 18 candidate models wrote a passage. Evaluation uses balanced accuracy
(mean per-class recall), not overall accuracy. Future validation should group by
`prompt_id` because test prompts are unseen; record split definitions and leakage checks.
Do not assume interactive example rows represent the hidden scoring set.

- [Configuration](project.yaml) defines this project's paths and dated competition facts.
- [Policy](POLICY.md) records rules, privacy and submission constraints.
- [Experiments](EXPERIMENTS.md) specifies reproducible evidence.
- [Review procedure](REVIEW.md) defines manual milestone reviews.
- [Central adoption record](../../docs/collaboration/projects/name-that-llm.md) tracks authority and receipts.

Engineering belongs in Codex Cloud; future training/inference should prefer Kaggle free
compute. No classifier, notebook, experiment runner or submission mechanism is included.
