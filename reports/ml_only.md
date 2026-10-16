# ML-only caught (in-sample)

> **Caveat.** Scores are on synthetic labels. ML thresholds are per-domain and not comparable across domains. A WEAK domain's numbers are not a calibrated result.

`ML_ONLY_CAUGHT` = `is_fraud=1` and ML flagged and **no rule** flagged the record. It is not a claim that ML is good: it counts only what the rules miss. Calibration is a label on the row, not a gate.

## Prevalence 0.02 (in-sample)

> Scored against synthetic labels; not a generalization estimate. Thresholds are per-domain and not comparable across domains.

| domain | calibration | status | ML flags | rule flags | ML-only flags | ML_ONLY_CAUGHT | val flags | val TP | val prec | val rec | test flags | test TP | test prec | test rec |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Civil Registry | WEAK | in-sample | 36 | 64 | 19 | 0 | 2 | 1 | 0.500 | 0.100 | 7 | 3 | 0.429 | 0.273 |
| MGNREGA Labor | CALIBRATED | in-sample | 97 | 144 | 32 | 0 | 12 | 11 | 0.917 | 0.458 | 21 | 11 | 0.524 | 0.500 |

### ML_ONLY_CAUGHT by fraud_type - Civil Registry (WEAK)

| fraud_type | events | ML_ONLY_CAUGHT | status |
|---|---|---|---|
| cross_scheme | 8 | 0 | not evaluable |
| invalid_mobile | 10 | 0 | in-sample |
| mega_family | 16 | 0 | in-sample |
| mobile_sharing | 10 | 0 | in-sample |
| suspicious_age | 10 | 0 | in-sample |
| underage_jobcard | 10 | 0 | in-sample |

### ML_ONLY_CAUGHT by fraud_type - MGNREGA Labor (CALIBRATED)

| fraud_type | events | ML_ONLY_CAUGHT | status |
|---|---|---|---|
| cross_scheme | 8 | 0 | not evaluable |
| free_money | 16 | 0 | in-sample |
| ghost_project | 23 | 0 | in-sample |
| impossible_human | 29 | 0 | in-sample |
| muster_cartel | 36 | 0 | in-sample |
| wage_theft | 34 | 0 | in-sample |

## Excluded: no calibrated threshold

> These domains' ML flags are not a detector (threshold is a fallback, not a calibrated operating point). Reported for completeness only.

| domain | calibration | ML flags | ML_ONLY_CAUGHT |
|---|---|---|---|
| PM-JAY Medical | UNCALIBRATED | 72 | 0 |

## Not evaluated

- 0.05: not evaluable - no ML scores at this prevalence (P4a wrote 0.02 only; the raw features and record sets differ, so re-scoring would need new per-level thresholds, which P4b must not add)
- 0.10: not evaluable - no ML scores at this prevalence (P4a wrote 0.02 only; the raw features and record sets differ, so re-scoring would need new per-level thresholds, which P4b must not add)
