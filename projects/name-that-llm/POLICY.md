# Name That LLM policy

Project ID: `name-that-llm`. Inherits the [shared operating policy](../POLICY.md) and
[subscription/budget configuration](../policy.yaml). Its initial Claude ceiling is
8 percentage points of total weekly allowance, inside the shared 15-point maximum.
No automatic or scheduled Claude reviews, paid APIs, extra-usage billing or paid fallbacks.

## Competition facts and authority

The prior audit read the official [overview](https://www.kaggle.com/competitions/name-that-llm/overview/abstract),
[data description](https://www.kaggle.com/competitions/name-that-llm/data) and
[rules](https://www.kaggle.com/competitions/name-that-llm/rules) on 2026-11-11.
No Kaggle call is made by this implementation. Rule acceptance, account eligibility,
team membership and compute access remain unverified; `rules_accepted: false` means
no verified acceptance is recorded here, not a claim about the owner's account.
The owner must recheck current rules and personally accept them before participation.

- Entry and team merger: 2027-01-06 at 23:59 UTC; final: 2027-01-13 at 23:59 UTC.
- Maximum team size 5; maximum 5 submissions/day and 2 selected finals.
- Submit through a Kaggle notebook. CPU and GPU runtime must each be at most 9 hours;
  internet access must be disabled during scoring.
- Read the scoring test set dynamically from the competition input. Write
  `submission.parquet` in the working directory with `id,model`: every test ID exactly
  once, no nulls, and labels from the official 18-name list. Do not hard-code example size.
- Freely/publicly available external data and pretrained models are permitted under the
  competition conditions. Record source, version, license and accessibility; no paid data
  generation or model API calls are authorized by this project policy.

## Privacy and reproducibility

The data page lists CC BY-SA 4.0, but the rules also impose data security and restrict
redistribution to nonparticipants. Do not put train/test data, passages, predictions or
private model artifacts in this public repository or a Claude review. Treat the rules
as controlling; obtain clarification before assuming a license permits redistribution.
Do not hand-label or use human predictions of validation/test records in submissions.

The winner license is listed as CC-BY 4.0; the rules include open-source/reproduction
obligations. Preserve licenses, provenance, training/inference code and environment
instructions so the owner can satisfy the final applicable terms. External-tool
reasonableness provisions are not blanket approval of a paid service or subscription.

Use only the `name-that-llm` namespaces from [project.yaml](project.yaml). Record prompt
split, balanced accuracy, per-class aggregate recall, input/model versions, seeds and
offline dependency/model packaging. Pin environment and notebook versions, and validate
submission schema, full test-ID coverage and nine-hour runtime on the intended compute.
These are future acceptance checks, not claims of completed validation.
