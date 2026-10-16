# Hybrid fraud detection - common entry points.
#
# PYTHONPATH=src is set for every python target. It is set with make's `export`
# rather than written inline (`PYTHONPATH=src python ...`) because GNU make on
# Windows runs recipes through cmd.exe by default, where the POSIX `VAR=value
# cmd` form is not valid; `export` works with both cmd.exe and sh (CI).
PYTHON ?= python
export PYTHONPATH := src

.PHONY: data train eval test lint api ui demo

# Generate the synthetic dataset (data/*.csv).
data:
	$(PYTHON) data_simulator.py

# Fit the per-domain IsolationForest and choose thresholds (reports/ml_scores.csv).
train: data
	$(PYTHON) -m fraud.ml

# Rule evaluation + ML-only report + HYBRID report (reports/*.json, reports/*.md).
# Depends on train: ml_only and hybrid read reports/ml_scores.csv, which is not
# committed (git-ignored *.csv), so a fresh checkout must fit the ML layer first.
# Exits non-zero if the reconciliation guard fails; the failure is NOT swallowed.
eval: train
	$(PYTHON) -m fraud.evaluate
	$(PYTHON) -m fraud.ml_only
	$(PYTHON) -m fraud.hybrid

# Run the test suite.
test:
	$(PYTHON) -m pytest -q

# Static checks.
lint:
	$(PYTHON) -m ruff check src tests

# Serve the generated reports read-only over HTTP.
api:
	$(PYTHON) -m uvicorn fraud.api:app --port 8000

# Open the read-only Streamlit dashboard.
ui:
	$(PYTHON) -m streamlit run app/dashboard.py

# Full local pass: generate data, run the reports, run the tests.
demo: data eval test
	@echo "open with: make ui"
