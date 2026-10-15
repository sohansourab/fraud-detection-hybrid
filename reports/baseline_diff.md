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

## P1e correction - Rule 025 join alignment (supersedes the Fix 2 numbers)

Fix 2 above introduced a regression: the `JobCardID -> BeneficiaryID` map was
built as

```python
dict(zip(beneficiaries["JobCardID"].dropna().astype(str),
         beneficiaries["BeneficiaryID"].astype(str)))
```

`dropna()` shortens the key column but not the value column, so `zip` paired
the two columns **by position**: every row after the first null job card got
the wrong beneficiary. On the synthetic data 1,406 of 1,407 pairs were wrong.

- Fix: build the map from the *same* filtered frame
  (`beneficiaries[["JobCardID", "BeneficiaryID"]].dropna(subset=["JobCardID"])`).
- Error figures (all from the synthetic dataset):

  | RULE_025 | count |
  |---|---|
  | before (P1a) | 99 |
  | old, buggy (P1d) | 616 |
  | corrected (P1e) | **660** |

- The old 616 was **not** a subset of the corrected 660: **304** of the P1d
  flags were spurious (produced only by the misalignment) and are dropped.
  Removed-vs-`flags_before.json` is still **0**, so the original 99 P1a flags
  all remain.
- Total flags: 2561 (P1d) -> **2605** (P1e); flagged records unchanged.
- Regression test: `tests/test_rule025_alignment.py` (fails on the P1d code,
  passes after the fix).

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

## Fix 4 - deterministic ids (seeded RNG instead of uuid4)

- Flag-id changes vs `flags_before.json`: **none** (added 0, removed 0).
- Why no baseline change: `AadhaarHash` (the only uuid user) is not read by any
  rule, so report ids are unaffected. The fix makes the *generated data*
  reproducible: two consecutive runs of `data_simulator.py` now produce a
  byte-identical `beneficiaries.csv` (verified by MD5).
- New helper `src/fraud/simulate.py` (`make_rng`, `aadhaar_hash`) builds ids from
  the config seed (42) instead of `uuid.uuid4()`.
- Regression test: `tests/test_simulate_determinism.py`.

## P2a - simulator injections + labels contract

- Data regenerated with cartel (Rule 017), procedure-mill (Rule 021) and
  blank-mobile hard-negative (Rule 013) injections, plus `data/labels.csv`
  (one row per scannable record). No rule logic changed.
- RULE_025 count: before 660 (P1e) -> after **890**.
- Total flags: 2605 -> 3339; flagged records 1776 -> 2270.
- `flags_after_p1d.json` was refreshed mechanically here. Because `data/` is
  gitignored, the snapshot now embeds an MD5 of each input table and
  `tests/test_baseline.py` fails with a "regenerate deliberately" message when
  the generated data changes.

## P2b - prevalence scaling

- Added `simulator.prevalence` (default 0.02). The simulator now scales every
  injected volume so the realised fraud rate is ~2% instead of ~24%.
- Structural floors keep Rules 004/013/017/021 able to fire: at least one
  cartel group, a mill group of >= `procedure_mill_threshold + 1`, one clone
  group, and a mega family larger than `max_family_size`.
- RULE_025 count: before 890 (P2a) -> after **16**.
- Total flags: 3339 -> **271**; flagged records 2270 -> **249**.
- Realised prevalence: 244 fraud records / 10087 scannable = **2.42%**.

## Summary

P1d/P1e changed only Rule 025:

| rule | before | after | added | removed |
|---|---|---|---|---|
| RULE_025 | 99 | 660 | 561 | 0 |
| all other rules | (unchanged) | (unchanged) | 0 | 0 |

Totals: flags 2044 -> 2605; flagged records 1776 -> 1776.

Later modules changed the *generated data*, not rule logic: P2a (injections +
labels) -> RULE_025 890 / total flags 3339; P2b (prevalence 0.02) -> RULE_025
16 / total flags 271. The current committed snapshot is
`tests/baseline/flags_after_p1d.json`; see the P2a and P2b sections above.



