# Official source recheck — 2026-11-11

Rechecked before implementation using public read-only Kaggle endpoints:

- [Rules](https://www.kaggle.com/competitions/squares-in-squares/rules):
  `competitions.PageService/ListPages`, competition ID 166661, rules page ID
  860187. SHA-256 of returned UTF-8 `content`:
  `ddfff7cd0fd336284cd437a5f36f25a6c0de061287ec0a000510d5b662793700`.
- [Evaluation](https://www.kaggle.com/competitions/squares-in-squares/overview/evaluation):
  content SHA-256 `ad72b2e8f06a5e98d356742e47e3e67fc96d2fc444bdb275e62517a39fde53d4`.
- [Data](https://www.kaggle.com/competitions/squares-in-squares/data):
  content SHA-256 `638348763893e67ce7b57a9e175ca9d3ba22ab67c8b040d336119619d25ff38e`.

Confirmed five-person teams, ten daily submissions, one selected final; coordinates
are decimal literals, angles radians, partial puzzles allowed with grid penalties.
The six CSV columns and dates in project.yaml remain consistent with current
competition metadata. Rules provide no competition dataset, restrict private code
sharing between teams, require reasonable accessibility/licensing of external tools,
and set winning-source licensing and reproduction obligations. No external packing
records are used. This public implementation contains synthetic fixtures only.
No competition-specific notebook execution requirement was found. Account eligibility,
team membership and acceptance are not verified; `rules_accepted` remains false.

The metric page HTML linked script version ID 362888901, while the public
`/api/v1/kernels/pull/metric/squares-in-squares` response identified notebook v20,
last run 2026-11-08T09:50:46.0918936Z. The v20 code was extracted and SHA-256 pinned
in metric.lock.json. The pin records the extraction algorithm; no official source
is redistributed. Parser limits in that source are 100 characters per literal,
absolute coordinates at most 10000 and angles at most 100 radians. Invalid,
missing and infeasible puzzles receive the grid penalty; accepted L is measured
from corners with 60-digit arithmetic.

Public competition metadata reports active competition metric version ID 77151.
Its source endpoint returned HTTP 401 without authentication, so correspondence
between that backend and notebook v20 is **not verified**. The adapter explicitly
reports the notebook version/hash. Do not interpret local results as a leaderboard
receipt. No rule acceptance, submission, remote notebook execution, Claude or paid
API call was made. Recheck before any future participation or pin update.
