"""API tests: read-only routes return the report file, 404 names the regen command.

A temp reports dir (via ``FRAUD_REPORTS_DIR``) is used so the tests never depend
on the repo's own ``reports/`` contents for the missing-file case.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

# TestClient comes from starlette; fastapi 0.143 + httpx 0.28 emit a harmless
# StarletteDeprecationWarning ("install httpx2 instead") on import. httpx is
# pinned in requirements.txt; the warning is not a regression.
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud import api  # noqa: E402

REPORTS = REPO_ROOT / "reports"

client = TestClient(api.app)

ENDPOINTS = {
    "/metrics": "metrics.json",
    "/ml-only": "ml_only.json",
    "/hybrid": "hybrid.json",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRAUD_REPORTS_DIR", raising=False)


@pytest.fixture
def temp_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp reports dir seeded with copies of the committed reports."""
    for name in ENDPOINTS.values():
        shutil.copy(REPORTS / name, tmp_path / name)
    monkeypatch.setenv("FRAUD_REPORTS_DIR", str(tmp_path))
    return tmp_path


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("route,filename", list(ENDPOINTS.items()))
def test_route_returns_file_json(
    route: str, filename: str, temp_reports: Path
) -> None:
    on_disk = json.loads((temp_reports / filename).read_text(encoding="utf-8"))
    response = client.get(route)
    assert response.status_code == 200
    assert response.json() == on_disk


@pytest.mark.parametrize("route", list(ENDPOINTS))
def test_missing_report_is_404_with_regen_command(
    route: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRAUD_REPORTS_DIR", str(tmp_path))  # empty dir
    response = client.get(route)
    assert response.status_code == 404
    assert "make eval" in response.json()["detail"]
