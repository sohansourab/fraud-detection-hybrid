"""Regression test for deterministic (seeded) id generation.

Bug fixed in P1d: ``AadhaarHash`` used ``uuid.uuid4()`` (unseeded), so the
dataset - and any id derived from it - changed on every regeneration.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud.simulate import aadhaar_hash, make_rng  # noqa: E402


def test_aadhaar_hash_is_deterministic_for_a_seed() -> None:
    first = [aadhaar_hash(make_rng(42)) for _ in [0]]  # fresh RNG each call
    rng_a, rng_b = make_rng(42), make_rng(42)
    assert [aadhaar_hash(rng_a) for _ in range(5)] == [aadhaar_hash(rng_b) for _ in range(5)]
    assert first[0] == aadhaar_hash(make_rng(42))


def test_aadhaar_hash_has_expected_shape() -> None:
    value = aadhaar_hash(make_rng(42))
    assert len(value) == 12
    assert value == value.upper()
    int(value, 16)  # parses as hexadecimal
