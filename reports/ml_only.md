# ML-only caught (in-sample)

> **Caveat.** Scores are on synthetic labels. The UNSEEN patterns were injected by the same simulator that generated the labels, so UNSEEN recall measures detection of our injected patterns, not generalization. ML thresholds are per-domain and not comparable across domains. A WEAK domain's numbers are not a calibrated result.

`ML_ONLY_CAUGHT` = `is_fraud=1` and ML flagged and **no rule** flagged the record. It is not a claim that ML is good: it counts only what the rules miss. Calibration is a label on the row, not a gate.

## Prevalence 0.02 (in-sample)

> Scored against synthetic labels; not a generalization estimate. Thresholds are per-domain and not comparable across domains.

| domain | calibration | status | ML flags | rule flags | ML-only flags | ML_ONLY_CAUGHT | KNOWN | UNSEEN | val flags | val TP | val prec | val rec | test flags | test TP | test prec | test rec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Civil Registry | WEAK | in-sample | 36 | 64 | 19 | 0 | 0 | 0 | 2 | 1 | 0.500 | 0.100 | 7 | 3 | 0.429 | 0.273 |
| MGNREGA Labor | CALIBRATED | in-sample | 105 | 144 | 40 | 1 | 0 | 1 | 14 | 11 | 0.786 | 0.423 | 21 | 10 | 0.476 | 0.385 |

### ML_ONLY_CAUGHT by fraud_type - Civil Registry (WEAK)

| fraud_type | events | ML_ONLY_CAUGHT | status |
|---|---|---|---|
| cross_scheme | 8 | 0 | not evaluable |
| invalid_mobile | 10 | 0 | in-sample |
| mega_family | 16 | 0 | in-sample |
| mobile_sharing | 10 | 0 | in-sample |
| suspicious_age | 10 | 0 | in-sample |
| underage_jobcard | 10 | 0 | in-sample |

### ML_ONLY_CAUGHT: KNOWN vs UNSEEN - Civil Registry (WEAK)

| group | ML_ONLY_CAUGHT | status |
|---|---|---|
| KNOWN | 0 | in-sample |
| UNSEEN | 0 | in-sample |
| total | 0 | in-sample |

| unseen_type | events | ML_ONLY_CAUGHT | status | note |
|---|---|---|---|---|
| unseen_just_under_limit | 0 | 0 | no unseen events injected | no unseen events injected for this domain |
| unseen_weekend_cluster | 0 | 0 | no unseen events injected | no unseen events injected for this domain |
| unseen_growing_amounts | 0 | 0 | no unseen events injected | no unseen events injected for this domain |

### ML_ONLY_CAUGHT by fraud_type - MGNREGA Labor (CALIBRATED)

| fraud_type | events | ML_ONLY_CAUGHT | status |
|---|---|---|---|
| cross_scheme | 8 | 0 | not evaluable |
| free_money | 16 | 0 | in-sample |
| ghost_project | 23 | 0 | in-sample |
| impossible_human | 29 | 0 | in-sample |
| muster_cartel | 36 | 0 | in-sample |
| unseen_just_under_limit | 12 | 1 | in-sample |
| wage_theft | 34 | 0 | in-sample |

### ML_ONLY_CAUGHT: KNOWN vs UNSEEN - MGNREGA Labor (CALIBRATED)

| group | ML_ONLY_CAUGHT | status |
|---|---|---|
| KNOWN | 0 | in-sample |
| UNSEEN | 1 | in-sample |
| total | 1 | in-sample |

| unseen_type | events | ML_ONLY_CAUGHT | status | note |
|---|---|---|---|---|
| unseen_just_under_limit | 12 | 1 | in-sample | 1 of 12, not evaluable as a recall estimate |
| unseen_weekend_cluster | 0 | 0 | no unseen events injected | no unseen events injected for this domain |
| unseen_growing_amounts | 0 | 0 | no unseen events injected | no unseen events injected for this domain |

## Excluded from the main table

> Reported for completeness only; these domains are not part of the main comparison. A pinned domain's note says why.

| domain | calibration | status | ML flags | ML_ONLY_CAUGHT | KNOWN | UNSEEN | note |
|---|---|---|---|---|---|---|---|
| PM-JAY Medical | CALIBRATED | in-sample | 81 | 27 | 0 | 27 | excluded: calibration rests on injected (unseen) patterns; see P4c |

### ML_ONLY_CAUGHT: KNOWN vs UNSEEN - PM-JAY Medical (CALIBRATED)

| group | ML_ONLY_CAUGHT | status |
|---|---|---|
| KNOWN | 0 | in-sample |
| UNSEEN | 27 | in-sample |
| total | 27 | in-sample |

| unseen_type | events | ML_ONLY_CAUGHT | status | note |
|---|---|---|---|---|
| unseen_just_under_limit | 0 | 0 | no unseen events injected | no unseen events injected for this domain |
| unseen_weekend_cluster | 14 | 14 | in-sample | 14 of 14, in-sample (injected patterns; not a generalization estimate) |
| unseen_growing_amounts | 13 | 13 | in-sample | 13 of 13, in-sample (injected patterns; not a generalization estimate) |

## Threshold-selection leakage (unseen rows in val)

> `ml.py` carves its val split out of the simulator's `train` split, so an injected unseen record that the simulator put in `train` can land in the val set whose precision chooses the threshold. That is leakage: the same typology we report UNSEEN recall on helped pick the operating point. The counts below are the evidence.

| domain | val unseen | val unseen flagged | val flags excl unseen | val TP excl unseen | val prec excl unseen | note |
|---|---|---|---|---|---|---|
| Civil Registry | 0 | 0 | 2 | 1 | 0.500 | no unseen rows in val (threshold not selected on unseen) |
| MGNREGA Labor | 3 | 0 | 14 | 11 | 0.786 | 3 unseen in val (0 flagged); excluding them val precision is 0.786 |
| PM-JAY Medical | 6 | 6 | 7 | 3 | 0.429 | 6 unseen in val (6 flagged); excluding them val precision is 0.429 (< 0.5 target), so the label rests on the injected rows |

## Not evaluated

- 0.05: not evaluable - no ML scores at this prevalence (P4a wrote 0.02 only; the raw features and record sets differ, so re-scoring would need new per-level thresholds, which P4b must not add)
- 0.10: not evaluable - no ML scores at this prevalence (P4a wrote 0.02 only; the raw features and record sets differ, so re-scoring would need new per-level thresholds, which P4b must not add)
