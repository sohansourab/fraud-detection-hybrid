"""Registry sanity checks."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud.rules import get_rules  # noqa: E402


def test_registry_has_16_rules() -> None:
    assert len(get_rules()) == 16


def test_rule_ids_are_unique() -> None:
    ids = [rule.id for rule in get_rules()]
    assert len(ids) == len(set(ids))


def test_rules_expose_required_metadata() -> None:
    for rule in get_rules():
        assert rule.id
        assert rule.domain
        assert rule.name
        assert isinstance(rule.severity, int)
