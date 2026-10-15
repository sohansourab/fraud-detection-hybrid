# Baseline diff after P1d bug fixes

Comparison target: `tests/baseline/flags_before.json` (captured in P1a).
`flags_before.json` is kept unchanged as history; the final snapshot is
`tests/baseline/flags_after_p1d.json`.

Each section lists the per-rule flag-id changes (`flags_after - flags_before`).
Untouched rules are expected to be identical, and are noted as such.

## Fix 1 - Rule 013 (clone detection): ignore null/blank mobile numbers

- Flag-id changes vs `flags_before.json`: **none** (added 0, removed 0).
- Why no baseline change: the current synthetic dataset contains 0 blank/null
  mobile numbers, so the false-positive path is not exercised by this data.
  Regression test `tests/test_rule013_blanks.py` covers it with a hand-made
  frame where four blank/null rows would previously be flagged as shared.

## Fix 2 - Rule 025 (cross-domain): exact id joins + MGNREGA mapping

- Flag-id changes vs `flags_before.json`: **RULE_025 only**.
  - RULE_025: before 99 -> after 616 (added 517, removed 0).
  - Newly added flags by domain: Civil Registry 95, MGNREGA Labor 316,
    PM-JAY Medical 106.
  - Every other rule: added 0, removed 0.
- Total flags: 2044 -> 2561. Flagged records unchanged at 1776 (Rule 025 only
  augments already-flagged records, it never creates new ones).
- Why: the old rule matched beneficiary ids by substring and could not link a
  MGNREGA transaction to a beneficiary at all, so MGNREGA never counted as a
  second scheme. Exact joins (`TransactionID -> JobCardID -> BeneficiaryID`,
  `ClaimID -> BeneficiaryID`) now let a beneficiary flagged in Civil + MGNREGA
  (or PM-JAY + MGNREGA) qualify, which is the rule's intent.
- Order dependency: the rule still reads `tables["flagged_records"]` (it must,
  to know what was flagged) but no longer depends on its order - each record is
  resolved independently and `flagged_domains` is reported sorted.
- Regression test: `tests/test_rule025_exact_join.py`.

## Fix 3 - Rule 021 (procedure mill): apply PROCEDURE_MILL_THRESHOLD

- Flag-id changes vs `flags_before.json`: **none** (added 0, removed 0).
- Finding (not a failure): the rule is now wired up correctly, but it stays
  inert on this synthetic dataset. The largest (hospital, procedure, month)
  count is 5, well below the threshold of 50. The simulator emits only ~180
  procedure-mill claims across 3 hospitals and 12 months, so no group reaches
  50/month. The rule is left in place; lowering the threshold or raising the
  injected volume is a simulator/eval decision for P2.
- The fix also removes an input-mutation bug: the old code added an
  `AdmissionMonth` column to the caller's DataFrame.
- Regression test: `tests/test_rule021_threshold.py` (a 51-claim group fires,
  and the input frame is unchanged).


