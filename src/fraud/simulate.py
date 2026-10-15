"""Deterministic helpers for the synthetic data simulator.

Id generation used to call ``uuid.uuid4()`` (unseeded), so regenerating the
dataset produced different ``AadhaarHash`` values on every run. These helpers
use a ``random.Random`` seeded from the config seed instead, so the generated
data - and therefore every downstream report id - is reproducible.
"""
from __future__ import annotations

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
