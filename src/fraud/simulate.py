"""Deterministic helpers for the synthetic data simulator.

Id generation used to call ``uuid.uuid4()`` (unseeded), so regenerating the
dataset produced different ``AadhaarHash`` values on every run. These helpers
use a ``random.Random`` seeded from the config seed instead, so the generated
data - and therefore every downstream report id - is reproducible.
"""
from __future__ import annotations

import hashlib
import random

from fraud.config import get_config


def make_rng(seed: int | None = None) -> random.Random:
    """Return a seeded RNG (defaults to the config seed)."""
    return random.Random(get_config().seed if seed is None else seed)


def aadhaar_hash(rng: random.Random) -> str:
    """Return a 12-character uppercase hex id.

    Same shape as the old ``uuid.uuid4().hex[:12].upper()`` but deterministic
    for a given RNG state.
    """
    return f"{rng.getrandbits(48):012X}"


def split_for(record_id: str, test_fraction: float = 0.2) -> str:
    """Deterministically assign a record to the ``train`` or ``test`` split.

    Uses an MD5 of the id (not the salted built-in ``hash``) so the split is
    stable across processes and runs.
    """
    digest = hashlib.md5(str(record_id).encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 1000 / 1000.0
    return "test" if bucket < test_fraction else "train"
