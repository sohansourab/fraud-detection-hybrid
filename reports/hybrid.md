# HYBRID (in-sample)

> **Caveat.** HYBRID combination is selected on validation rows excluding unseen typologies, then reported once on test. All numbers are on synthetic labels; unseen recall measures detection of injected patterns, not generalization. Only CALIBRATED domains are reported in the main table.

`TP` = known (rule-injected) fraud caught; `OTHER_FRAUD` = flagged fraud with no rule injection (the unseen typologies); `FP` = flagged `is_fraud=0`. Precision is `TP / (TP + FP)`; recall is `TP / (TP + FN)` over known fraud. Unseen recall is reported separately. `cross-rule overlap` is a separate rule diagnostic (`evaluate.py`'s OTHER_FRAUD): flagged records injected for a *different* rule. It is not the aggregate `OTHER_FRAUD` column.

## Selection (validation rows, unseen excluded)

> Selection domains (CALIBRATED only): MGNREGA Labor. Rows used: 806.

| combination | val F1 | val precision | val recall | val TP | val FP | val FN | selected |
|---|---|---|---|---|---|---|---|
| rule_only | 1.000 | 1.000 | 1.000 | 23 | 0 | 0 | yes |
| max | 0.676 | 0.511 | 1.000 | 23 | 22 | 0 | no |
| weighted_w0.3 | 0.667 | 0.812 | 0.565 | 13 | 3 | 10 | no |
| weighted_w0.5 | 0.757 | 1.000 | 0.609 | 14 | 0 | 9 | no |
| weighted_w0.7 | 0.978 | 1.000 | 0.957 | 22 | 0 | 1 | no |
| rule_first | 0.939 | 0.885 | 1.000 | 23 | 3 | 0 | no |

**No candidate beat the rule-only baseline** (val F1 1.000); the selected combination is `rule_only`.

> **The selection told us nothing.** The rules are perfect on the selection rows (rule-only FP 0, FN 0), so F1 cannot exceed 1.000 and the rule-only baseline is trivially optimal. The candidate comparison below has no room to differ; it only shows which candidates add false positives.

## Test (reported once, including unseen rows)

| domain | detector | flags | TP | FP | OTHER_FRAUD | FN | cross-rule overlap | precision | recall | F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| MGNREGA Labor | HYBRID = rules-only (selected) | 22 | 22 | 0 | 0 | 0 | 3 | 1.000 | 1.000 | 1.000 |
| MGNREGA Labor | ML_ONLY | 21 | 10 | 11 | 0 | 12 | 3 | 0.476 | 0.455 | 0.465 |

> `HYBRID = rules-only (selected)`: the selected combination is `rule_only`, so HYBRID and RULES_ONLY are the same detector and agree by construction. They are shown as one row.

### HYBRID known vs unseen recall (test)

| domain | known caught / known fraud | known recall | unseen caught / unseen fraud | unseen recall |
|---|---|---|---|---|
| MGNREGA Labor | 22 / 22 | 1.000 | 0 / 4 | not evaluable |

> MGNREGA Labor unseen: 4 unseen events; fewer than 10 is not a recall estimate.

### ML val to test gap (main finding)

| domain | split | flags | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|---|---|
| MGNREGA Labor | val | 14 | 11 | 3 | 12 | 0.786 | 0.478 | 0.595 |
| MGNREGA Labor | test | 21 | 10 | 11 | 12 | 0.476 | 0.455 | 0.465 |

> MGNREGA Labor ML precision falls from 0.786 (val) to 0.476 (test): a drop of 0.310. The ML score is unstable across splits.

## Excluded (WEAK / UNCALIBRATED)

> Only CALIBRATED domains enter the main table. These domains' val evidence does not support a calibrated operating point.

| domain | calibration | val flags | val TP | val precision | note |
|---|---|---|---|---|---|
| Civil Registry | WEAK | 2 | 1 | 0.500 | excluded: WEAK (target met, val evidence too thin) |
| PM-JAY Medical | UNCALIBRATED | 7 | 3 | 0.429 | excluded: UNCALIBRATED (target not met on selection rows) |

## Sensitivity (not selected)

> `PM-JAY threshold recomputed on selection rows`: threshold 0.6329 -> 2 flags, 2 TP, precision 1.000, `WEAK`. Sensitivity only: the committed threshold is kept for the report. This variant is not selected.

## Leakage

> Selection uses validation rows only, with the unseen typologies excluded. See the 'Threshold-selection leakage' section of reports/ml_only.md: ml.py carves its val split out of the simulator's train split, so unseen rows would otherwise leak into selection. Here they never choose a threshold or a combination rule.
