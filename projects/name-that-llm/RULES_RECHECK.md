# Official-source recheck — 2026-11-11

Rechecked **before coding**, without entering the competition, accepting rules,
downloading competition data, or submitting anything. Read the published competition
rules and incorporated foundational rules through Kaggle's public page service because
the rules HTML page returned an application shell. This is a dated engineering note,
not account eligibility or rule acceptance verification.

Sources:

- [Competition rules](https://www.kaggle.com/competitions/name-that-llm/rules):
  public `competitions.PageService/GetPage`, competition ID 170484, page `Rules`
  (published page ID 885036); also read page `foundational-rules`.
- [Official overview and evaluation](https://www.kaggle.com/competitions/name-that-llm/overview/abstract).
- [Official data description](https://www.kaggle.com/competitions/name-that-llm/data).
- [Official timeline](https://www.kaggle.com/competitions/name-that-llm/overview/timeline):
  also read page `timeline` and public `competitions.CompetitionService/GetCompetition`.

Constraints relevant to this baseline: notebook scoring with internet disabled and
CPU/GPU runtime at most nine hours; balanced accuracy across 18 named models;
`submission.parquet` with `id,model`, exact unique test ID coverage, no nulls, and valid
labels. Hidden test prompts are unseen; interactive examples are not representative.
The implementation reads all test rows dynamically and groups validation by prompt.

Rules retain team size five, five submissions/day and two selected finals. External
inputs/tools have accessibility and licensing conditions; this baseline uses no external
training corpus, pretrained weights, or model APIs. Data security restricts redistribution
outside participants despite the stated CC BY-SA 4.0 data license. Foundational rules
prohibit hand labeling/human predictions of validation/test records, private sharing
outside teams, and require competition code shared publicly to also be shared on the
competition's Kaggle forum or notebooks under an appropriate open source license.
The source here has a project-local MIT license. The owner still needs to handle
Kaggle-side code sharing before participation; this task does not post to Kaggle.

Entry and merger metadata say 2027-01-06 23:59 UTC. The published timeline says final
2027-01-13 23:59 UTC, while current competition metadata reports a deadline of
2027-01-14 23:59:00.817 UTC. Retain the earlier published timeline date in project.yaml;
do not rely on the extra day without organizer clarification. This discrepancy has no
bearing on synthetic CI. Recheck all official pages before real experiments or entry.

No Claude invocation, paid API, competition dataset access, Kaggle execution, submission,
rule acceptance, team registration or nine-hour runtime verification occurred here.
