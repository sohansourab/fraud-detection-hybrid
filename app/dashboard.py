"""Read-only Streamlit dashboard over the generated reports.

Three pages: Metrics, ML-only, Hybrid. Each page reads its JSON report (to
confirm the report exists) and renders the matching markdown report verbatim.
Nothing is computed here and no number is added: every figure shown comes from
the files ``make eval`` writes, and the in-sample caveat is part of that file.

Run with ``make ui``.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS = REPO_ROOT / "reports"

# page label -> (json report, markdown report)
PAGES: dict[str, tuple[str, str]] = {
    "Metrics": ("metrics.json", "metrics.md"),
    "ML-only": ("ml_only.json", "ml_only.md"),
    "Hybrid": ("hybrid.json", "hybrid.md"),
}

st.set_page_config(page_title="Fraud detection reports", layout="wide")

# Visible on every page.
st.warning("SYNTHETIC DATA - these reports are in-sample on simulator labels.")

st.title("Fraud detection reports")

page = st.sidebar.radio("Report", list(PAGES))
json_name, md_name = PAGES[page]

json_path = REPORTS / json_name
md_path = REPORTS / md_name

if not json_path.is_file() or not md_path.is_file():
    st.error("Report missing. Regenerate it with `make eval`.")
else:
    json.loads(json_path.read_text(encoding="utf-8"))  # read-only existence check
    st.markdown(md_path.read_text(encoding="utf-8"))  # table + caveat, verbatim
