# Hybrid fraud detection - common entry points.
PYTHON ?= python
export PYTHONPATH := src

.PHONY: test eval data

test:
	$(PYTHON) -m pytest -q

eval:
	$(PYTHON) -m fraud.evaluate

data:
	$(PYTHON) data_simulator.py
