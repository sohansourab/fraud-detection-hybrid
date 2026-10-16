# Evaluation metrics (in-sample)

> **In-sample caveat.** In-sample: every rule is scored against the same injections the simulator planted. The rules were written to catch those patterns, so precision and recall are optimistic and are NOT a generalization estimate.

Rule-level precision, recall and F1 only: each rule emits a binary flag, so PR-AUC does not apply. `not evaluable` = fewer than 10 injected events at that prevalence.

## Prevalence 0.02 (in-sample)

> Scored against the simulator's own injections at this prevalence; not a generalization estimate.

### Scaling types (counts scale with prevalence)

| rule | fraud_type | status | flagged | injected | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| RULE_001 | invalid_mobile | in-sample | 10 | 10 | 10 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_002 | underage_jobcard | in-sample | 18 | 10 | 10 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_003 | suspicious_age | in-sample | 10 | 10 | 10 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_013 | mobile_sharing | in-sample | 10 | 10 | 10 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_005 | impossible_human | in-sample | 36 | 29 | 28 | 0 | 1 | 1.00 | 0.97 | 0.98 |
| RULE_006 | ghost_project | in-sample | 23 | 23 | 23 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_007 | wage_theft | in-sample | 34 | 34 | 34 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_008 | free_money | in-sample | 16 | 16 | 16 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_017 | muster_cartel | in-sample | 36 | 36 | 36 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_009 | time_travel | in-sample | 18 | 10 | 10 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_010 | bio_mismatch | in-sample | 10 | 10 | 10 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_011 | massive_upcoding | in-sample | 11 | 11 | 11 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_012 | blacklisted_hospital | in-sample | 10 | 10 | 10 | 0 | 0 | 1.00 | 1.00 | 1.00 |

### Flat types (do not measure prevalence sensitivity)

Fixed/floored injected volume: `procedure_mill`, `cross_scheme`, and `mega_family` where its floor binds.

| rule | fraud_type | status | flagged | injected | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| RULE_004 | mega_family | in-sample | 21 | 16 | 16 | 5 | 0 | 0.76 | 1.00 | 0.86 |
| RULE_021 | procedure_mill | in-sample | 51 | 51 | 51 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_025 | cross_scheme | in-sample | 48 | 24 | 24 | 2 | 0 | 0.92 | 1.00 | 0.96 |

## Prevalence 0.05 (in-sample)

> Scored against the simulator's own injections at this prevalence; not a generalization estimate.

### Scaling types (counts scale with prevalence)

| rule | fraud_type | status | flagged | injected | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| RULE_001 | invalid_mobile | in-sample | 18 | 18 | 18 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_002 | underage_jobcard | in-sample | 23 | 15 | 15 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_003 | suspicious_age | in-sample | 10 | 10 | 10 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_013 | mobile_sharing | in-sample | 20 | 20 | 20 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_005 | impossible_human | in-sample | 75 | 69 | 67 | 0 | 2 | 1.00 | 0.97 | 0.99 |
| RULE_006 | ghost_project | in-sample | 56 | 56 | 56 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_007 | wage_theft | in-sample | 88 | 92 | 88 | 0 | 4 | 1.00 | 0.96 | 0.98 |
| RULE_008 | free_money | in-sample | 46 | 46 | 46 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_017 | muster_cartel | in-sample | 96 | 96 | 96 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_009 | time_travel | in-sample | 24 | 16 | 16 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_010 | bio_mismatch | in-sample | 6 | 11 | 6 | 0 | 5 | 1.00 | 0.55 | 0.71 |
| RULE_011 | massive_upcoding | in-sample | 27 | 27 | 27 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_012 | blacklisted_hospital | in-sample | 27 | 27 | 27 | 0 | 0 | 1.00 | 1.00 | 1.00 |

### Flat types (do not measure prevalence sensitivity)

Fixed/floored injected volume: `procedure_mill`, `cross_scheme`, and `mega_family` where its floor binds.

| rule | fraud_type | status | flagged | injected | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| RULE_004 | mega_family | in-sample | 22 | 16 | 16 | 5 | 0 | 0.76 | 1.00 | 0.86 |
| RULE_021 | procedure_mill | in-sample | 51 | 51 | 51 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_025 | cross_scheme | in-sample | 94 | 24 | 24 | 0 | 0 | 1.00 | 1.00 | 1.00 |

## Prevalence 0.10 (in-sample)

> Scored against the simulator's own injections at this prevalence; not a generalization estimate.

### Scaling types (counts scale with prevalence)

| rule | fraud_type | status | flagged | injected | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| RULE_001 | invalid_mobile | in-sample | 36 | 36 | 36 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_002 | underage_jobcard | in-sample | 38 | 31 | 30 | 0 | 1 | 1.00 | 0.97 | 0.98 |
| RULE_003 | suspicious_age | in-sample | 14 | 14 | 14 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_004 | mega_family | in-sample | 37 | 32 | 32 | 4 | 0 | 0.89 | 1.00 | 0.94 |
| RULE_013 | mobile_sharing | in-sample | 43 | 43 | 43 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_005 | impossible_human | in-sample | 135 | 130 | 127 | 0 | 3 | 1.00 | 0.98 | 0.99 |
| RULE_006 | ghost_project | in-sample | 103 | 103 | 103 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_007 | wage_theft | in-sample | 169 | 174 | 169 | 0 | 5 | 1.00 | 0.97 | 0.99 |
| RULE_008 | free_money | in-sample | 97 | 97 | 97 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_017 | muster_cartel | in-sample | 180 | 180 | 180 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_009 | time_travel | in-sample | 42 | 34 | 34 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_010 | bio_mismatch | in-sample | 9 | 20 | 9 | 0 | 11 | 1.00 | 0.45 | 0.62 |
| RULE_011 | massive_upcoding | in-sample | 70 | 70 | 70 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_012 | blacklisted_hospital | in-sample | 52 | 52 | 52 | 0 | 0 | 1.00 | 1.00 | 1.00 |

### Flat types (do not measure prevalence sensitivity)

Fixed/floored injected volume: `procedure_mill`, `cross_scheme`, and `mega_family` where its floor binds.

| rule | fraud_type | status | flagged | injected | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| RULE_021 | procedure_mill | in-sample | 51 | 51 | 51 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| RULE_025 | cross_scheme | in-sample | 268 | 24 | 24 | 0 | 0 | 1.00 | 1.00 | 1.00 |

## Detectors

| detector | status | precision | recall | F1 |
|---|---|---|---|---|
| RULES_ONLY | in-sample | n/a | n/a | n/a |
| ML_ONLY | not built (P4) | n/a | n/a | n/a |
| HYBRID | not built (P4) | n/a | n/a | n/a |
