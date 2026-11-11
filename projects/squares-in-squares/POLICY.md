# Squares in Squares policy

Project ID: `squares-in-squares`. Inherits the [shared operating policy](../POLICY.md) and
[subscription/budget configuration](../policy.yaml). Its initial Claude ceiling is
4 percentage points of total weekly allowance, inside the shared 15-point maximum.
No automatic or scheduled Claude reviews, paid APIs, extra-usage billing or paid fallbacks.

## Competition facts and authority

The prior audit read the official [overview](https://www.kaggle.com/competitions/squares-in-squares/overview),
[data description](https://www.kaggle.com/competitions/squares-in-squares/data) and
[rules](https://www.kaggle.com/competitions/squares-in-squares/rules) on 2026-11-11.
The baseline rechecked public rules and metric sources; see [audit](RULES_AUDIT.md).
The runtime makes no Kaggle network calls. Rule acceptance, account eligibility,
team membership and compute access remain unverified; `rules_accepted: false` means
no verified acceptance is recorded here. The owner must recheck current rules and
personally accept them before participation.

- Entry and team merger: 2027-07-11 at 23:59 UTC; final: 2027-07-18 at 23:59 UTC.
- Progress milestones: 2027-01-17 and 2027-04-18, both at 23:59 UTC.
- Maximum team size 5; maximum 10 submissions/day and 1 selected final.
- Submit CSV with `id,n,square_id,x,y,angle`. IDs are unique integers; square IDs run
  from 0 to n-1 within each supplied puzzle. Coordinates are decimal literals (scientific
  notation allowed); angles are radians. Symbolic expressions are not accepted.
- All supplied unit squares in a puzzle must have non-overlapping interiors. The metric
  computes enclosing side length L from corners; do not submit L as an extra column.
- Partial puzzle sets are allowed. Missing puzzles receive `ceil(sqrt(n))/sqrt(n) - 1`.
  Preserve valid placements and check the current official metric's invalid-input handling.
- The audit found no competition-specific notebook execution requirement. This project
  nevertheless uses cloud compute and prefers Kaggle free CPU; general notebook limits
  and account quota still apply. Do not copy Name That LLM's offline/nine-hour rule here.

## Privacy and reproducibility

The data page lists CC0; the rules say no competition dataset is provided, alongside a
general data-security clause. Do not treat this as permission to republish private
artifacts or other teams' work. External packing records, code and pretrained models
need provenance, licensing and an accessibility check under the reasonableness standard.
Winning solutions carry open-source (CC BY 4.0 or Apache 2.0 in the specific rules) and
reproduction obligations; the full rules control any apparent inconsistency.

Use only the `squares-in-squares` namespaces from [project.yaml](project.yaml). Pin the
[official metric](https://www.kaggle.com/code/metric/squares-in-squares) version/hash;
record puzzle sets, seeds, search budget, environment, feasibility checks, decimal output
precision and per-puzzle/total aggregate scores. Preserve checkpoints privately with hashes.
Validate serialized CSV again, rather than relying on a floating-point search tolerance
as proof of valid geometry. The offline baseline enforces these checks; real search artifacts remain private.
