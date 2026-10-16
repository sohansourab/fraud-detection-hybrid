"""Rule engine: one class per rule plus a registry.

Importing this package populates the registry. Import order is significant:
it fixes the order rules are evaluated in (and therefore flag order).
"""
from fraud.rules.base import Rule
from fraud.rules.registry import get_rules, register

# Canonical order: civil -> mgnrega -> pmjay -> cross-domain.
from fraud.rules import civil, mgnrega, pmjay, cross  # noqa: E402,F401

__all__ = ["Rule", "get_rules", "register"]
