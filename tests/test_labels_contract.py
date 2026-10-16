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
from collections import Counter
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
    # Unseen typologies (P2e) are fraud by design but carry *no* rule id.
    fraud_rows = labels[labels["is_fraud"] == 1]
    unseen_rows = fraud_rows[fraud_rows["fraud_type"].str.startswith("unseen_")]
    ruled_rows = fraud_rows[~fraud_rows["fraud_type"].str.startswith("unseen_")]
    assert ruled_rows["injected_rule_id"].ne("").all()
    assert unseen_rows["injected_rule_id"].eq("").all()


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


# ---------------------------------------------------------------------------
# 4. Unseen typologies (P2e): counts, existing counts unchanged, no rule fires
# ---------------------------------------------------------------------------

#: Per-type injected events at 0.02 prevalence as of P2d (before P2e). The
#: unseen injections draw from a separate RNG stream, so these must not move.
P2D_PER_TYPE_COUNTS = {
    "bio_mismatch": 10,
    "blacklisted_hospital": 10,
    "cross_scheme": 24,
    "free_money": 16,
    "ghost_project": 23,
    "hard_negative_blank_mobile": 40,
    "impossible_human": 29,
    "invalid_mobile": 10,
    "massive_upcoding": 11,
    "mega_family": 16,
    "mobile_sharing": 10,
    "muster_cartel": 36,
    "procedure_mill": 51,
    "suspicious_age": 10,
    "time_travel": 10,
    "underage_jobcard": 10,
    "wage_theft": 34,
}
UNSEEN_TYPES = (
    "unseen_growing_amounts",
    "unseen_just_under_limit",
    "unseen_weekend_cluster",
)


def _event_counts(labels: pd.DataFrame) -> dict[str, int]:
    """Per-fraud_type injected events (a row may carry ``A|B``)."""
    counts: Counter = Counter()
    for types in labels["fraud_type"].astype(str):
        for name in types.split("|"):
            name = name.strip()
            if name:
                counts[name] += 1
    return dict(counts)


def _unseen_event_ids(labels: pd.DataFrame) -> dict[str, set[str]]:
    events: dict[str, set[str]] = {}
    for record_id, types in zip(labels["record_id"], labels["fraud_type"]):
        for name in str(types).split("|"):
            if name.startswith("unseen_"):
                events.setdefault(name, set()).add(str(record_id))
    return events


def test_unseen_typologies_present_and_existing_counts_unchanged() -> None:
    data = _generated("a")[0] / "data"
    labels = pd.read_csv(data / "labels.csv", keep_default_na=False)
    counts = _event_counts(labels)

    # 1. Existing per-type counts are identical to P2d.
    for name, expected in P2D_PER_TYPE_COUNTS.items():
        assert counts.get(name, 0) == expected, (name, counts.get(name, 0), expected)

    # 2. The three unseen types are present, each with >= min_events events,
    #    labelled is_fraud=1 and an empty injected_rule_id.
    cfg = get_config()
    assert sorted(t for t in counts if t.startswith("unseen_")) == list(UNSEEN_TYPES)
    for name in UNSEEN_TYPES:
        assert counts[name] >= cfg.simulator.min_events_per_type, name

    rows = labels[labels["fraud_type"].isin(UNSEEN_TYPES)]
    assert (rows["is_fraud"] == 1).all()
    assert rows["injected_rule_id"].eq("").all()


def test_unseen_typologies_do_not_fire_any_rule() -> None:
    dest = _generated("a")[0]
    labels = pd.read_csv(dest / "data" / "labels.csv", keep_default_na=False)

    from fraud.evaluate import scan_flags  # local: keeps sklearn off the fast path

    rule_flags = scan_flags(dest)
    flagged = set().union(*rule_flags.values()) if rule_flags else set()

    fired = {
        name: sorted(ids & flagged)
        for name, ids in _unseen_event_ids(labels).items()
        if ids & flagged
    }
    assert fired == {}, f"a rule fired on an unseen typology: {fired}"
