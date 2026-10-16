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

## P2c - min events per type + cross-scheme injection

Simulator/config only; no rule, detection or evaluation code changed.

- New `simulator.min_events_per_type` (default 10). After prevalence scaling any
  fraud type below the floor is raised to it, *unless* the raise would push
  total fraud above `1.5 x prevalence x scannable`. Rows are mutated in place,
  so the scannable count (and the cap) is unchanged; types that could not be
  raised are printed with the reason.
- New `simulator.cross_scheme` (25 beneficiaries; combos Civil+MGNREGA,
  MGNREGA+PM-JAY, Civil+PM-JAY). Each beneficiary gets a flagged per-domain
  event in every scheme of its combo (Civil: underage + job card; MGNREGA:
  DaysWorked > 15; PM-JAY: discharge before admission), all labelled
  `fraud_type=cross_scheme`, `injected_rule_id=RULE_025`.
- Old -> new per-type injected events (prevalence 0.02, in-sample):

  | fraud_type | P2b | P2c | | fraud_type | P2b | P2c |
  |---|---|---|---|---|---|---|
  | bio_mismatch | 0 | 0 | | mega_family | 16 | 16 |
  | blacklisted_hospital | 7 | **10** | | mobile_sharing | 5 | 5 |
  | cross_scheme | 0 | **50** | | muster_cartel | 36 | 36 |
  | free_money | 16 | 16 | | procedure_mill | 51 | 51 |
  | ghost_project | 23 | 23 | | suspicious_age | 6 | 6 |
  | hard_negative_blank_mobile | 40 | 40 | | time_travel | 7 | 7 |
  | impossible_human | 29 | 29 | | underage_jobcard | 3 | **10** |
  | invalid_mobile | 7 | 7 | | wage_theft | 34 | 34 |
  | massive_upcoding | 11 | 11 | | **total** | 291 | 351 |

- Floor at 0.02: raised `blacklisted_hospital` 8->10 and `underage_jobcard`
  3->10. **Not** raised (cap reached): `bio_mismatch` (0), `invalid_mobile` (7),
  `mobile_sharing` (5), `suspicious_age` (6), `time_travel` (7) - each would
  push total fraud above the 1.5x cap (304). These stay "not evaluable".
- RULE_025 count: before 16 (P2b) -> after **69**. All 50 cross-scheme records
  are flagged; the 25 injected beneficiaries each resolve to >= 2 schemes with
  **0 unresolved** links through the exact P1e joins.
- Total flags: 271 -> **384**; flagged records 249 -> **309**.
- Realised prevalence: 244/10087 (2.42%) -> 304/10145 (**2.997%**, at the cap).
- Regression test: `tests/test_cross_scheme.py`.

## P2d - cross_scheme resize (25 -> 12 beneficiaries) and P2 close-out

Data and docs only; no rule or evaluation code changed.

**Decision.** `simulator.cross_scheme.beneficiaries` 25 -> **12**. The injection
is a *fixed count*, not prevalence-driven. At 25 beneficiaries (50 records) the
dedicated Rule 025 pattern was ~20% of all injected fraud at 0.02 prevalence and
consumed the 1.5x floor cap; 12 beneficiaries still yield **24 records**, above
`min_events_per_type` (10), while leaving headroom for the floor and keeping the
cross-scheme share of fraud modest.

**P2c per-type table (prevalence 0.02 / 0.05 / 0.10, in-sample):**

| fraud_type | 0.02 | 0.05 | 0.10 | fraud_type | 0.02 | 0.05 | 0.10 |
|---|---|---|---|---|---|---|---|
| bio_mismatch | 0 | 11 | 20 | mobile_sharing | 5 | 20 | 43 |
| blacklisted_hospital | 10 | 30 | 54 | muster_cartel | 36 | 96 | 180 |
| cross_scheme | 50 | 50 | 50 | procedure_mill | 51 | 51 | 51 |
| free_money | 16 | 46 | 97 | suspicious_age | 6 | 10 | 14 |
| ghost_project | 23 | 56 | 103 | time_travel | 7 | 14 | 34 |
| impossible_human | 29 | 69 | 130 | underage_jobcard | 10 | 15 | 31 |
| invalid_mobile | 7 | 18 | 36 | wage_theft | 34 | 92 | 174 |
| massive_upcoding | 11 | 27 | 70 | mega_family | 16 | 16 | 32 |

**P2d per-type table (prevalence 0.02, in-sample):**

| fraud_type | events | | fraud_type | events |
|---|---|---|---|---|
| bio_mismatch | 10 | | mobile_sharing | 10 |
| blacklisted_hospital | 10 | | muster_cartel | 36 |
| cross_scheme | **24** | | procedure_mill | 51 |
| free_money | 16 | | suspicious_age | 10 |
| ghost_project | 23 | | time_travel | 10 |
| hard_negative_blank_mobile | 40 | | underage_jobcard | 10 |
| impossible_human | 29 | | wage_theft | 34 |
| invalid_mobile | 10 | | mega_family | 16 |
| massive_upcoding | 11 | | **total** | 350 |

- Floor at 0.02: with the smaller cross-scheme block the cap now has room, so
  every thin type was **raised** to the floor: `bio_mismatch` 0->10,
  `blacklisted_hospital` 7->10, `invalid_mobile` 7->10, `mobile_sharing` 5->10,
  `suspicious_age` 6->10, `time_travel` 7->10, `underage_jobcard` 3->10. **No
  type is left under 10 / "not evaluable"** at 0.02.
- RULE_025 count: before **69** (P2c) -> after **48**. All 24 cross-scheme
  records are flagged and the 12 injected beneficiaries each resolve to >= 2
  schemes with **0 unresolved** links through the exact P1e joins.
- Realised prevalence at 0.02: 2.997% (P2c) -> **2.996%** (303 fraud / 10115
  scannable).
- Total flags: 384 -> **362**; flagged records 309 -> **308**.
- Input-hash change (deliberate refresh of `flags_after_p1d.json`):

  | table | old md5 | new md5 |
  |---|---|---|
  | beneficiaries | `47fb9cabf74b2bef1f11a73f0520bd22` | `e6a698421161e7a38dc0ee248b801761` |
  | mgnrega | `33260b9513b5b210277842aa006ba4f7` | `7f2fcf07dff223e454ed6aebc554f431` |
  | pmjay | `465d100a4c973215c3d013c4c199654f` | `3675414b8f906b985a2217085c5cc61e` |

- Determinism: two consecutive runs produce byte-identical `beneficiaries.csv`,
  `transactions_mgnrega.csv`, `transactions_pmjay.csv` and `labels.csv` (MD5
  match).
- **In-sample warning:** RULE_025's recall on `cross_scheme` is 1.0 *by
  construction* - the simulator injects exactly the multi-scheme pattern the
  rule detects, so this is an in-sample figure, not a generalization estimate.

## P2e - unseen typologies (patterns with no matching rule)

Simulator, config and labels only; no rule, ML or evaluation code changed.

**Three unseen typologies** were added under `simulator.unseen` (all
`enabled` by default), each labelled `fraud_type=unseen_*` with an empty
`injected_rule_id` and `is_fraud=1`. They are *appended* with a dedicated RNG
stream (`seed + 400`) after the min-events floor, so the global RNG stream and
every existing per-type count are untouched.

| typology | pattern | events (0.02) |
|---|---|---|
| `unseen_just_under_limit` | MGNREGA payments at 95-99% of a 3500 approval limit (days = 15, amount = days x rate) | 12 |
| `unseen_weekend_cluster` | 14 PM-JAY claims at one hospital across the July 2024 weekends | 14 |
| `unseen_growing_amounts` | 13 PM-JAY claims at one hospital, amounts rising 3%/month over 12 months | 13 |

**Existing per-type counts are identical to P2d** (in-sample, 0.02):

| fraud_type | P2d | P2e | fraud_type | P2d | P2e |
|---|---|---|---|---|---|
| bio_mismatch | 10 | 10 | mobile_sharing | 10 | 10 |
| blacklisted_hospital | 10 | 10 | muster_cartel | 36 | 36 |
| cross_scheme | 24 | 24 | procedure_mill | 51 | 51 |
| free_money | 16 | 16 | suspicious_age | 10 | 10 |
| ghost_project | 23 | 23 | time_travel | 10 | 10 |
| hard_negative_blank_mobile | 40 | 40 | underage_jobcard | 10 | 10 |
| impossible_human | 29 | 29 | wage_theft | 34 | 34 |
| invalid_mobile | 10 | 10 | mega_family | 16 | 16 |
| massive_upcoding | 11 | 11 | **existing total** | 350 | 350 |

**Rule flags on the unseen records (design goal 0):** 0 for
`unseen_growing_amounts` (13), `unseen_just_under_limit` (12) and
`unseen_weekend_cluster` (14) - see `reports/unseen_rule_flags.md`. No existing
rule generalises to any of the three patterns. The injections were designed to
avoid the rules; they were **not** tuned to reach zero.

- Scannable records: 10115 -> **10154** (+39 unseen records). Realised
  prevalence: 2.996% (303/10115) -> **3.368%** (342/10154). The extra unseen
  fraud is expected and is *not* scaled back (that would move existing counts).
- Total flags unchanged at **362**; flagged records unchanged at **308**;
  RULE_025 unchanged at **48**. The unseen records fire no rule, so the flag
  snapshot changes only in its input hashes.
- Input-hash change (deliberate refresh of `flags_after_p1d.json`):

  | table | P2d md5 | P2e md5 |
  |---|---|---|
  | beneficiaries | `e6a698421161e7a38dc0ee248b801761` | `e6a698421161e7a38dc0ee248b801761` (unchanged) |
  | mgnrega | `7f2fcf07dff223e454ed6aebc554f431` | `c969b7b5f456cec32da01dc25ec1cc24` |
  | pmjay | `3675414b8f906b985a2217085c5cc61e` | `3fafa2a717440cbd44371a480b35ba5e` |

- Determinism: two consecutive runs produce byte-identical
  `beneficiaries.csv`, `transactions_mgnrega.csv`, `transactions_pmjay.csv` and
  `labels.csv` (MD5 match).
- Regression tests: `tests/test_labels_contract.py`
  (`test_unseen_typologies_present_and_existing_counts_unchanged`,
  `test_unseen_typologies_do_not_fire_any_rule`).
- **In-sample warning:** these are injected events at the 0.02 run, not a
  generalization estimate.

## P3b - reconciliation guard + flat-type classification

Evaluation-harness only: no rule logic and no generated data changed, so total
flags, flagged records and the baseline snapshot are unchanged.

- **Fix - explicit `OTHER_FRAUD` bucket.** The earlier guard showed the old FP
  definition was too narrow: a flag on a *fraud* record injected with a
  **different** rule is not a TP for this rule and not an FP in the `is_fraud`
  sense. It is now its own bucket and the identity
  `flagged == TP + FP + OTHER_FRAUD` holds for every row (asserted in
  `rule_scores` and by `assert_reconciliation`; `reports/metrics.json` carries
  `reconciliation_ok` / `reconciliation_violations`).
  - `TP` = `is_fraud=1` and injected with this rule;
  - `OTHER_FRAUD` = `is_fraud=1` and injected with a different rule;
  - `FP` = `is_fraud=0` (unchanged).
  - Precision stays `TP / (TP + FP)`; recall denominator stays the records
    injected with this rule. `OTHER_FRAUD` is measured, never folded into TP or
    FP.
- Per-rule `OTHER_FRAUD` counts (from `reports/metrics.json`; the full table is
  in `reports/metrics.md`):

  | rule | 0.02 | 0.05 | 0.10 |
  |---|---|---|---|
  | RULE_002 | 8 | 8 | 8 |
  | RULE_004 | 0 | 1 | 1 |
  | RULE_005 | 8 | 8 | 8 |
  | RULE_009 | 8 | 8 | 8 |
  | RULE_025 | 22 | 70 | 244 |
  | all other rules | 0 | 0 | 0 |

  RULE_025's overlap scales with prevalence (22 -> 70 -> 244): unrelated
  typologies increasingly place records in multiple schemes, so Rule 025
  co-fires on records the simulator injected for other rules. This is real
  cross-rule overlap, not a false positive, and it means the per-rule numbers
  are not independent.
- No metric definition changed beyond the bucket above; detection is untouched
  (e.g. RULE_002 recall at 0.10 is still 0.97 from its own FN, not redefined).
- **`mega_family` classification (rechecked against the actual counts):** flat
  only while its injected count equals the structural floor
  (`max_family_size + 1` = 16). Observed: 0.02 -> 16 (flat), 0.05 -> 16 (flat),
  0.10 -> 32 (scaling). The decision is documented in `reports/metrics.md`
  ("Flat-type classification"), generated from the payload (not hand-typed).
- Regression tests: `tests/test_evaluate.py`
  (`test_reconciliation_buckets_three_kinds`,
  `test_reconciliation_guard_detects_missing_bucket`,
  `test_reconciliation_guard_accepts_consistent_rows`,
  `test_payload_records_floor_and_reconciliation`, and
  `test_repo_flags_reconcile` - no xfail).

## P4b-rerun - calibration expectation change (data change, not a model change)

P2e appended the unseen typologies, which changed `reports/ml_scores.csv`
(P4a refit on the new data: per-domain `IsolationForest`, thresholds re-chosen
on val). P4b was then re-run on the new scores. No feature, threshold, rule,
simulator or metric definition changed here - only the data the ML layer sees,
so the calibration label is expected to move. These are the new hardcoded
expectations in `tests/test_ml_only.py` (the old outcome is kept as history).

| domain | old outcome | new outcome | old val (flags/TP/prec) | new val (flags/TP/prec) | reason |
|---|---|---|---|---|---|
| Civil Registry | WEAK | WEAK | 2 / 1 / 0.500 | 2 / 1 / 0.500 | unchanged: too few val flags to call it calibrated |
| MGNREGA Labor | CALIBRATED | CALIBRATED | 12 / 11 / 0.917 | 14 / 11 / 0.786 | still calibrated; the added unseen rows shift val precision |
| PM-JAY Medical | UNCALIBRATED | CALIBRATED | not persisted (old report stored no val for excluded rows; precision was < 0.5) | 13 / 9 / 0.692 | the injected unseen claims are ML-detectable, so val precision crossed the target |

- The old values come from the pre-P2e committed `reports/ml_only.json`
  (`db4dfdb`); the new values come from the regenerated report. Civil and
  MGNREGA keep their outcome; PM-JAY's label moved.
- PM-JAY stays in the excluded block even though it now reads CALIBRATED: its
  calibration rests on the injected (unseen) patterns, so it is not a
  generalization result. It stays out of the main table until P4c explains why
  it should count (`PINNED_EXCLUDED` in `src/fraud/ml_only.py`).
- `ML_ONLY_CAUGHT` is split into KNOWN (non-`unseen_*`) and UNSEEN
  (`unseen_*`), with UNSEEN broken out by typology and any type under 10 events
  marked not evaluable. In-sample at prevalence 0.02: Civil 0/0, MGNREGA 0/1
  (unseen_just_under_limit), PM-JAY 0/27 (weekend_cluster 14, growing_amounts
  13). The KNOWN column is 0 everywhere: the rules catch every injected
  in-sample typology, so every ML-only catch is an injected unseen pattern.
- Regression tests: `tests/test_ml_only.py`
  (`test_report_calibration_expectations`,
  `test_known_and_unseen_sum_to_ml_only_caught`).

## P4b-rerun follow-up - threshold-selection leakage (unseen rows in val)

P2e injected the unseen typologies *before* the train/val carve, so some of them
land in the val split that chooses the ML threshold. This is leakage: the same
typologies whose UNSEEN recall is reported helped pick the operating point.

- `data/labels.csv` carries **no** `val` split: the simulator assigns
  `train`/`test` only (`split_for`, `test_fraction=0.2`). `ml.py` then carves
  its `val` out of the simulator's `train` (`_carve_val`, stratified on
  `is_fraud`, `val_fraction=0.2`, seed 42). So "does val contain unseen?" is a
  question about the *effective* split in `reports/ml_scores.csv`, and the
  answer is yes: 9 of the 39 unseen rows (23%).
- Split counts per unseen typology (labels split has no val column):

  | domain | unseen_type | labels train | labels test | ML train | ML val | ML test | total |
  |---|---|---|---|---|---|---|---|
  | MGNREGA Labor | unseen_just_under_limit | 8 | 4 | 5 | 3 | 4 | 12 |
  | PM-JAY Medical | unseen_growing_amounts | 13 | 0 | 8 | 5 | 0 | 13 |
  | PM-JAY Medical | unseen_weekend_cluster | 9 | 5 | 8 | 1 | 5 | 14 |

- Consequence for the calibration label (val precision target 0.5):

  | domain | val unseen | val unseen flagged | val flags excl unseen | val TP excl unseen | val prec excl unseen | effect |
  |---|---|---|---|---|---|---|
  | Civil Registry | 0 | 0 | 2 | 1 | 0.500 | none (no unseen injected) |
  | MGNREGA Labor | 3 | 0 | 14 | 11 | 0.786 | none (unseen in val not flagged) |
  | PM-JAY Medical | 6 | 6 | 7 | 3 | 0.429 | decisive: below 0.5, so CALIBRATED rests on the leaked rows |

  PM-JAY's val precision with the unseen rows is 0.692 (13 flags, 9 TP; 6 of the
  9 TP are unseen). Drop those 6 rows and it is 0.429 (7 flags, 3 TP) - below
  the target, i.e. the pre-P2e `UNCALIBRATED` outcome. The label change recorded
  above is therefore a leakage effect, not evidence the model generalizes.
- Not fixed in P4b-rerun (reporting only). P4c must not reuse these
  val-chosen thresholds as if val were independent; a follow-up should hold the
  unseen typologies out of threshold selection entirely and re-choose the
  threshold on known types only.
- Reported (not hand-typed) in `reports/ml_only.md` /
  `reports/ml_only.json` ("Threshold-selection leakage" + per-row `leakage`).
- Regression tests: `tests/test_ml_only.py`
  (`test_val_leakage_is_reported`; `test_known_and_unseen_sum_to_ml_only_caught`
  now also pins the Civil "no unseen events injected" wording and the MGNREGA
  "1 of 12, not evaluable as a recall estimate" note).

## P4c - HYBRID with unseen excluded from selection

The HYBRID combination is selected on validation rows with the unseen typologies
excluded (module P4c), then reported **once** on test. No feature, ML threshold,
rule, simulator or `evaluate` metric definition changed; a new `hybrid` section
was added to `configs/default.yaml` and a `HybridConfig` to `src/fraud/config.py`.

- Selection set = val rows whose `fraud_type` has no `unseen_*` token. Rows per
  domain: Civil 322, MGNREGA 806, PM-JAY 494.
- **Calibration expectations changed** (committed thresholds; unseen excluded):

  | domain | P4b-rerun | P4c | val flags | val TP | val precision |
  |---|---|---|---|---|---|
  | Civil Registry | WEAK | WEAK | 2 | 1 | 0.500 |
  | MGNREGA Labor | CALIBRATED | CALIBRATED | 14 | 11 | 0.786 |
  | PM-JAY Medical | CALIBRATED | **UNCALIBRATED** | 7 | 3 | 0.429 |

  PM-JAY drops from CALIBRATED to UNCALIBRATED once the 6 leaked unseen val rows
  are removed from the metrics: the P4b-rerun label rested on them (see the
  leakage section above). This matches the pre-P2e outcome.
- Sensitivity (not selected): recomputing PM-JAY's threshold on the selection
  rows gives 0.6329 -> 2 flags, 2 TP, precision 1.000 -> WEAK. Reported only as
  a variant; the committed threshold is kept.
- Combination selection (val F1 on the CALIBRATED domain, MGNREGA, 806 rows):
  rule_only 1.000, `max` 0.676, weighted w0.3 0.667, w0.5 0.757, w0.7 0.978,
  rule_first 0.939. **No candidate beat the rule-only baseline**, so the
  selected combination is `rule_only` (a HYBRID that does not beat rules on
  known typologies is not reported as an improvement).
- Test, MGNREGA (reported once, including unseen): HYBRID = rules-only
  (selected) 22 TP / 0 FP / 0 OTHER / 0 FN (P 1.000, R 1.000, F1 1.000);
  ML_ONLY 10 / 11 / 0 / 12 (P 0.476, R 0.455, F1 0.465). HYBRID is shown as
  one row, not two, because the selected combination is `rule_only` and so
  HYBRID and RULES_ONLY are the same detector by construction. HYBRID known vs
  unseen recall on test: known 22 / 22 (1.000); unseen 0 / 4 is **not
  evaluable** (4 events is not a recall estimate).
- Routing (enforced in code): only CALIBRATED domains enter the main table;
  WEAK and UNCALIBRATED go to the excluded block with their val counts. Civil
  (WEAK) and PM-JAY (UNCALIBRATED) are excluded.
- Reported (not hand-typed) in `reports/hybrid.md` / `reports/hybrid.json`.
- Regression tests: `tests/test_hybrid.py`
  (`test_selection_rows_drop_unseen_val_rows`,
  `test_select_combination_refuses_test_rows`,
  `test_calibration_expectations`,
  `test_only_calibrated_domains_in_main_table`,
  `test_detector_rows_reconcile`,
  `test_selection_set_has_no_room`,
  `test_unseen_recall_is_not_evaluable`,
  `test_cross_rule_overlap_is_reported`).

### P4c review checks

Two checks run after the first P4c report, both now encoded in the report.

- **Check 1 - did the selection have room to differ? No.** On the MGNREGA
  selection rows (806) the rules are perfect: rule-only TP 23, FP 0, FN 0
  (`test_selection_set_has_no_room`). F1 cannot exceed 1.000, so the rule-only
  baseline is trivially optimal and the candidate comparison carries no
  information about the candidates; it only shows which candidates add false
  positives. The report states this explicitly.
- **Check 2 - is `OTHER_FRAUD` 0 a filter artefact? No, but it is a different
  quantity.** The aggregate `OTHER_FRAUD` column counts flagged *unseen* fraud;
  on MGNREGA test neither detector flags any of the 4 unseen, so it is 0. The
  `evaluate.py` cross-rule overlap (a rule flags a fraud record injected for a
  different rule) is a separate diagnostic and is **3** on MGNREGA test (2 of
  them RULE_025). It sits in all three domains (Civil 2, MGNREGA 3, PM-JAY 4 on
  test), not only Civil/PM-JAY. The report now carries a `cross-rule overlap`
  column so the two are never confused (`test_cross_rule_overlap_is_reported`).
- **ML instability is the main finding.** MGNREGA ML_ONLY precision falls from
  0.786 (val) to 0.476 (test), a drop of 0.310; F1 0.595 -> 0.465. The ML score
  is unstable across splits, which is why the only calibrated domain's ML signal
  does not support a HYBRID that beats rules.
- **Rename - `other_fraud` -> `unseen_caught` (report + code + tests).** The
  aggregate bucket counts flagged *unseen* fraud, whereas `OTHER_FRAUD` in
  `metrics.md` / `evaluate.py` is the cross-rule overlap. Two definitions under
  one name would mislead a reader who sees both. The aggregate column is now
  `unseen_caught`; `evaluate.py`'s cross-rule overlap is kept as the separate
  `cross_rule_overlap` diagnostic. `metrics.md` and `evaluate.py` are unchanged.

## P8 - packaging and read-only presentation (no result change)

Packaging only: a `Makefile`, a CI workflow, a read-only FastAPI surface
(`src/fraud/api.py`), a read-only Streamlit dashboard (`app/dashboard.py`) and a
README "Running it" section. No rule, ML, simulator, HYBRID or `evaluate` metric
definition changed, and no generated report was hand-edited.

- `reports/hybrid.json` MD5 changed `BFA38A83...` -> `FB10A87E...` solely because
  the aggregate key was renamed (`other_fraud` -> `unseen_caught`) in the P4c
  review; no result changed. Current MD5: `FB10A87E08FE2D2DD477F7548267C898`.
- Regression tests: `tests/test_api.py` (each route returns its report file; a
  missing report is a 404 naming `make eval`) and `tests/test_readme_metrics.py`
  (every 3-decimal figure in `README.md` must sit inside the
  `<!-- BEGIN GENERATED: hybrid -->` block, and `## Limitations` must have none).

## Summary

P1d/P1e changed only Rule 025:

| rule | before | after | added | removed |
|---|---|---|---|---|
| RULE_025 | 99 | 660 | 561 | 0 |
| all other rules | (unchanged) | (unchanged) | 0 | 0 |

Totals: flags 2044 -> 2605; flagged records 1776 -> 1776.

Later modules changed the *generated data*, not rule logic: P2a (injections +
labels) -> RULE_025 890 / total flags 3339; P2b (prevalence 0.02) -> RULE_025
16 / total flags 271; P2c (min-events floor + cross-scheme) -> RULE_025 69 /
total flags 384; P2d (cross_scheme 25->12) -> RULE_025 48 / total flags 362;
P2e (unseen typologies) -> RULE_025 48 / total flags 362 (unchanged; the unseen
records fire no rule, so only the input hashes moved).
The current committed snapshot is `tests/baseline/flags_after_p1d.json`; see the
P2a-P2e sections above.

## B905 pass (zip strictness)

No logic change: every edit adds `strict=` to an existing `zip()` call. Some
single-line calls were reflowed across lines so the extra parameter fits; the
token stream is otherwise identical, and no variable, return value or condition
moved.

- `strict=` added at 25 zip sites: 20 in `src/fraud/rules/` (civil 5, cross 4,
  mgnrega 5, pmjay 6), 2 in `src/fraud/evaluate.py` and `src/fraud/hybrid.py`,
  and 3 in tests (`tests/test_cross_scheme.py` x2, `tests/test_labels_contract.py`).
- All 25 are length-matched by construction: each zips columns of one frame, or
  a column with the same boolean-mask selection of the same frame.
- 0 runtime `strict=` failures: `pytest -q` 66 passed and `make demo` exit 0.
- Caveat: `strict=True` proves the lengths matched on the tested data and paths,
  not on every possible input.
- 0 change in output: `reports/` MD5s unchanged (`metrics.md`
  `4AD522FF4521147CC981C36C300280E9`, `ml_only.md`
  `A66C14D966708078A1446EEE7645AAC6`, `hybrid.json`
  `FB10A87E08FE2D2DD477F7548267C898`, `hybrid.md`
  `4E4508CD65B370052BCE2E7677376057`); `tests/baseline/flags_after_p1d.json`
  unchanged.
- Acceptance conflict: `ruff` B905 also fires on the five call sites outside
  `src/fraud/rules/`, so those five were fixed rather than excluded, and B905 is
  now enabled in `ruff.toml` with no ignore list.

## AGENT-FIX parser

Verifier-only change in `src/fraud/agent/verifier.py` (the agent branch,
`AGENT-FIX`). The citation parser now accepts multi-citations in three written
forms: `[E2, E4]`, `[E2][E4]` and `[E2] [E4]`.

- `evidence_ids()` reads every id in a bracketed group (comma- or
  semicolon-separated) and every adjacent group, so `[E2, E4]` yields
  `["E2", "E4"]` and `[E2][E4]` yields `["E2", "E4"]`.
- Every cited id must exist in the evidence list, and each sentence still needs
  at least one valid id: a sentence citing only an unknown id, or mixing a
  known id with an unknown one, is unsupported.
- The sentence splitter is unchanged (`split_sentences()`), and no other
  verifier logic changed.
- Documented in the `verifier.py` module docstring; regression-tested in
  `tests/test_agent_fix.py` (`test_parser_accepts_multi_citations`,
  `test_parser_rejects_id_not_in_evidence`).
- No rule, simulator, ML, HYBRID or `evaluate` metric definition changed, and
  no generated report was hand-edited.



