"""Real-data track (IEEE-CIS loader, module R1).

This package is deliberately separate from the synthetic pipeline under
``fraud.*`` so the two tracks cannot accidentally share state. Only
``fraud.external.ieee_cis`` is public today.
"""
from __future__ import annotations

from fraud.external.ieee_cis import (
    IeeeCisConfig,
    LoadReport,
    build_ieee_cis,
    frame_md5,
    load_external_config,
    load_ieee_cis,
    resolve_input_file,
)

__all__ = [
    "IeeeCisConfig",
    "LoadReport",
    "build_ieee_cis",
    "frame_md5",
    "load_external_config",
    "load_ieee_cis",
    "resolve_input_file",
]
