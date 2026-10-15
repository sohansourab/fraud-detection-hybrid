"""Rule registry.

Concrete rules self-register with ``@register``. Registration order is the
order in which rules are imported (see ``fraud.rules.__init__``) and is what
determines the order of flags within a record.
"""
from __future__ import annotations

from typing import Type, TypeVar

from fraud.rules.base import Rule

_REGISTRY: dict[str, Rule] = {}

R = TypeVar("R", bound=Type[Rule])


def register(cls: R) -> R:
    """Instantiate ``cls`` and add it to the registry."""
    instance = cls()
    if instance.id in _REGISTRY:
        raise ValueError(f"Duplicate rule id: {instance.id}")
    _REGISTRY[instance.id] = instance
    return cls


def get_rules() -> list[Rule]:
    """Return every registered rule, in registration order."""
    return list(_REGISTRY.values())
