"""Read-only FastAPI surface over the generated reports.

No business logic lives here: every route returns a JSON report exactly as the
pipeline wrote it, or a 404 naming the ``make`` target that regenerates it.
The numbers are synthetic and in-sample; see ``reports/metrics.md``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"

app = FastAPI(title="Fraud detection reports (read-only, synthetic data)")


def reports_dir() -> Path:
    """Reports directory. ``FRAUD_REPORTS_DIR`` overrides it (used by tests)."""
    override = os.environ.get("FRAUD_REPORTS_DIR")
    return Path(override) if override else DEFAULT_REPORTS_DIR


def _read_report(name: str, make_target: str) -> Any:
    """Load one report verbatim, or raise a 404 naming the regen command."""
    path = reports_dir() / name
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                f"{name} not found at {path}; regenerate it with `make {make_target}`"
            ),
        )
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Any:
    return _read_report("metrics.json", "eval")


@app.get("/ml-only")
def ml_only() -> Any:
    return _read_report("ml_only.json", "eval")


@app.get("/hybrid")
def hybrid() -> Any:
    return _read_report("hybrid.json", "eval")
