# Data Sources

## IEEE-CIS Fraud Detection (real data)

- **Dataset:** IEEE-CIS Fraud Detection (a Kaggle competition). Distribution files
  `train_transaction.csv` and `train_identity.csv`.
- **Source URL:** https://www.kaggle.com/competitions/ieee-fraud-detection
  - Confirmed download origin: **TODO** — the actual URL the files were downloaded
    from was not recorded and cannot be verified from the files on disk.
- **Download date:** **TODO** — not recorded (left for the user; not guessed).
- **Terms:** **TODO** — competition **Rules** tab not read (Kaggle pages were not
  reachable from this environment).
- **Citation:** **TODO** — competition page not reachable, so the official citation
  could not be retrieved.
- **Local location:** `data/external/ieee-cis/` (git-ignored). In this checkout the
  CSVs sit one directory level deeper than the config path, i.e.
  `train_transaction.csv/train_transaction.csv` and
  `train_identity.csv/train_identity.csv`; the R1 loader resolves both layouts.

## Verified facts (module R1 / R1b)

All numbers below were recomputed from the local files; nothing here is hand-edited.

- **Row counts:** 590,540 transactions; 144,233 identity rows. After the LEFT join
  the transaction count is unchanged at 590,540 (no dropped rows).
- **Fraud rate:** 3.499% overall.
- **Splits** (quantile time split on `TransactionDT`, from `configs/external.yaml`):

  | split | rows    | fraud rate |
  |-------|---------|------------|
  | train | 354,324 | 3.38%      |
  | val   | 118,108 | 3.90%      |
  | test  | 118,108 | 3.44%      |

  - **Boundaries:** `TransactionDT <= 8,745,782.4` = train;
    `8,745,782.4 < TransactionDT <= 12,192,853.6` = val; `> 12,192,853.6` = test.
  - **Boundary-tie counts:** 0 rows equal the val boundary (8,745,782.4) and 0 rows
    equal the test boundary (12,192,853.6). Both boundaries are fractional and
    `TransactionDT` is an integer, so no row ties exactly; the `<=` rule is
    therefore satisfied trivially, and the nearest integer timestamps also have 0
    rows at each cut.
- **Processed file:** `data/external/ieee-cis/processed.parquet`
  (git-ignored), produced by the R1 loader at commit `5b50255`.
  - **MD5:** `ee1dabb7bf570b5b28ee60abec2edb67`
- **Note:** this is **real** data and is **not comparable** to the synthetic 2%
  prevalence used elsewhere in this repo. The val split has a higher fraud rate
  (3.90%) than train (3.38%) or test (3.44%).
