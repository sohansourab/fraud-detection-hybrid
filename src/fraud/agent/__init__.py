"""Agent layer: grounded, per-case review of already flagged records.

The tools read only the scanner's input tables and the rule registry. The
ground-truth labels are never loaded here, and are never handed to the model.
"""
from __future__ import annotations

__all__ = ["tools", "llm", "verifier", "investigator", "run"]
