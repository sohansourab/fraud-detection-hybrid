"""Module P2a contract tests for the synthetic data simulator.

Covers three things:

1. Detection code must never read ``data/labels.csv`` (labels are ground truth,
   not an input to the rules or the pipeline).
2. The generator is deterministic: the same seed produces byte-identical CSVs
   and labels.
3. ``labels.csv`` has exactly one row per scannable record, with the expected
   new injections present and correctly labelled (blank-mobile rows are
   hard negatives: ``is_fraud == 0``).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud.config import get_config  # noqa: E402

SIMULATOR = REPO_ROOT / "data_simulator.py"

DATA_FILES = [
    "beneficiaries.csv",
    "transactions_mgnrega.csv",
    "transactions_pmjay.csv",
    "labels.csv",
]

# Generate the dataset at most once per tag; the determinism test uses two tags.
_CACHE: dict[str, tuple[Path, dict[str, str]]] = {}


@pytest.fixture(scope="session", autouse=True)
def _cleanup_generated_dirs():
    yield
    for dest, _ in _CACHE.values():
        shutil.rmtree(dest, ignore_errors=True)


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _generate(dest: Path) -> dict[str, str]:
    """Run the simulator in ``dest`` and return md5s of the generated files."""
    env = dict(os.environ, PYTHONUTF8="1")
    result = subprocess.run(
        [sys.executable, str(SIMULATOR)],
        cwd=dest,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return {name: _md5(dest / "data" / name) for name in DATA_FILES}


def _generated(tag: str) -> tuple[Path, dict[str, str]]:
    if tag not in _CACHE:
        dest = Path(tempfile.mkdtemp(prefix=f"fraud_sim_{tag}_"))
        _CACHE[tag] = (dest, _generate(dest))
    return _CACHE[tag]


# ---------------------------------------------------------------------------
# 1. Detection code must not know about labels.csv
# ---------------------------------------------------------------------------

def test_detection_code_never_references_labels() -> None:
    candidates = list((REPO_ROOT / "src" / "fraud" / "rules").rglob("*.py"))
    pipeline = REPO_ROOT / "src" / "fraud" / "pipeline.py"
    if pipeline.exists():
        candidates.append(pipeline)

    offenders: list[str] = []
    for path in candidates:
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "labels" in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
    assert offenders == [], f"detection code references labels: {offenders}"


# ---------------------------------------------------------------------------
# 2. Determinism
# ---------------------------------------------------------------------------

def test_generator_is_byte_identical_across_runs() -> None:
    _, hashes_a = _generated("a")
    _, hashes_b = _generated("b")
    assert hashes_a == hashes_b, f"{hashes_a} != {hashes_b}"


# ---------------------------------------------------------------------------
# 3. labels.csv shape and content
# ---------------------------------------------------------------------------

def test_labels_one_row_per_scannable_record_and_injections() -> None:
    data = _generated("a")[0] / "data"
    ben = pd.read_csv(data / "beneficiaries.csv")
    mgn = pd.read_csv(data / "transactions_mgnrega.csv")
    pmj = pd.read_csv(data / "transactions_pmjay.csv")
    labels = pd.read_csv(data / "labels.csv", keep_default_na=False)

    assert list(labels.columns) == [
        "record_id", "domain", "is_fraud", "fraud_type", "injected_rule_id", "split",
    ]
    assert len(labels) == len(ben) + len(mgn) + len(pmj)
    assert labels["record_id"].is_unique

    cfg = get_config()
    counts = labels["fraud_type"].value_counts().to_dict()
    # P2a injections that make the previously-inert rules fire; volumes are
    # scaled by prevalence (P2b) but floored so these still fire.
    assert counts.get("procedure_mill", 0) >= cfg.pmjay.procedure_mill_threshold + 1
    assert counts.get("muster_cartel", 0) > 0
    assert counts.get("hard_negative_blank_mobile", 0) == int(
        len(ben) * cfg.simulator.blank_mobile_rate
    )

    # Blank-mobile rows are hard negatives, never fraud.
    blanks = labels[labels["fraud_type"] == "hard_negative_blank_mobile"]
    assert (blanks["is_fraud"] == 0).all()
    assert blanks["injected_rule_id"].eq("").all()

    # Every injected fraud row carries a rule id; blank/clean rows do not.
    fraud_rows = labels[labels["is_fraud"] == 1]
    assert fraud_rows["injected_rule_id"].ne("").all()


def test_repo_labels_match_repo_data_if_present() -> None:
    data = REPO_ROOT / "data"
    labels_path = data / "labels.csv"
    if not labels_path.is_file():
        pytest.skip("data/labels.csv not generated in this checkout")

    labels = pd.read_csv(labels_path, keep_default_na=False)
    ben = pd.read_csv(data / "beneficiaries.csv")
    mgn = pd.read_csv(data / "transactions_mgnrega.csv")
    pmj = pd.read_csv(data / "transactions_pmjay.csv")
    assert len(labels) == len(ben) + len(mgn) + len(pmj)
