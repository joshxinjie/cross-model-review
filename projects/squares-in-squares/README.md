# Squares in Squares

Offline deterministic baseline for `n=1..1000`: row-major unit squares with
zero rotation and side `ceil(sqrt(n))`. The aggregate grid score is
`28.93766991655058`. This is a feasibility baseline, with no improvement claim.
No competition data, placements, submissions or private run artifacts are committed.

## Run and resume

Python 3.12 on Linux/POSIX, one CPU process. Install the exact runtime versions in
[requirements.lock](requirements.lock) into a virtual environment. The runner requires
a clean committed project tree and records the source SHA plus package source hash.
From the repository root:

```sh
export PYTHONPATH=projects/squares-in-squares
# Public read only; no account, rule acceptance, kernel execution or submission.
curl -fsSL https://www.kaggle.com/api/v1/kernels/pull/metric/squares-in-squares -o /tmp/squares-kernel.json
python -m sis.extract_metric /tmp/squares-kernel.json /tmp/squares-official.py
python -m sis --run-id baseline-001 --puzzles 1:1000 --max-steps 0 \
  --cpu-seconds 0 --official-source /tmp/squares-official.py
# Bounded exploratory search; repeat the same command to resume.
python -m sis --run-id search-001 --puzzles 5:10 --seed 42 --max-steps 100 \
  --cpu-seconds 10 --official-source /tmp/squares-official.py
```

All generated config, checkpoint and manifest files stay in ignored
`private/<run-id>/`. CSV exists only in memory; no submission file is emitted.
The source export is external and hash checked before execution. The extraction
command refuses a newer notebook or changed source: re-audit and deliberately
update the pin instead of trusting a moving latest version.

The search perturbs one square's center and angle, accepting only independently
certified non-increasing enclosing sides (including plateau moves). The incumbent
always starts at the valid grid. An explicit seed and global step determine each
proposal. Checkpoints atomically store decimal strings, full configuration, completed
step, acceptance count and cumulative CPU, with a SHA-256 corruption check. Resume
revalidates every packing and rejects changes to configuration or solver code.
The CPU timer interrupts an unfinished proposal and replays that step next time;
setup, checkpoint validation/I/O and official scoring are outside the search budget.
`--steps-per-call` permits deterministic split-run tests. No parallel workers or GPU.
This small hill climber is a bounded starting point, not a competitive optimizer.

## Geometry and scoring contracts

- `sis.packing` writes exact decimal strings with `id,n,square_id,x,y,angle`;
  angles are radians. Reads reject nonfinite/symbolic values, duplicate IDs,
  incomplete puzzles and extra columns. Local exponent bounds prevent resource
  exhaustion and deliberately reject some extreme official-parser inputs.
- `sis.geometry` imports no official code. Axis-aligned packings use exact rational
  rectangles and a sweep; rotated packings use interval corners and separating
  axes at 50, 100 and 200 decimal digits. Boundary validation checks every corner
  against an optional explicit origin and side. Uncertain contacts fail closed.
  Enclosing sides are exact rational upper bounds; decimal serialization is
  re-read and revalidated before scoring.
- `sis.metric` verifies [metric.lock.json](metric.lock.json) and runtime versions,
  then calls the official per-puzzle evaluator serially. It preserves official
  missing/invalid penalties and rejection reasons without its multiprocessing
  pool or details-file side effect. The pin is **public notebook v20**, not a
  claim of parity with an authenticated backend metric. See [audit](RULES_AUDIT.md).

## Tests

```sh
SIS_OFFICIAL_SOURCE=/tmp/squares-official.py python -m pytest -q
```

Install both repository `requirements-dev.txt` and this project's `requirements.lock`
for the full suite. Shared CI installs only shared dependencies; solver tests explicitly
skip if the optional `mpmath` runtime is absent. Tests certify and
round-trip all 500,500 grid squares, exercise edge/corner contacts, rotations,
sub-double overlaps, boundaries, bad CSV, checkpoint corruption, CPU deadlines,
split-run equivalence and manifest schema compatibility. Official integration
tests compare synthetic grids and failures against the pinned notebook and its
`score` entry point. Only those integration tests skip without the external source;
there is no download during tests. Test details files stay in temporary storage.

[Policy](POLICY.md), [experiment contract](EXPERIMENTS.md),
[configuration](project.yaml), and [manual review procedure](REVIEW.md) apply.
No Claude reviews, paid APIs, Kaggle execution or submissions are invoked.
