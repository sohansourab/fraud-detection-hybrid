"""Abstract base class for a single deterministic fraud rule."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

#: Columns every rule result must expose.
RESULT_COLUMNS = ["record_id", "rule_id", "evidence_json"]


class Rule(ABC):
    """Base class for a fraud rule.

    Subclasses set the metadata attributes below and implement ``evaluate``.
    ``severity`` is the legacy ``risk_score`` and is added to a record's total
    risk score once per flag.
    """

    id: str
    domain: str
    name: str
    pattern: str
    description: str
    severity: int

    @abstractmethod
    def evaluate(self, tables: dict[str, pd.DataFrame], cfg: Any) -> pd.DataFrame:
        """Return a frame with columns :data:`RESULT_COLUMNS`."""

    def flag(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """Build the legacy flag dict for this rule (key order preserved)."""
        return {
            "rule_id": self.id,
            "name": self.name,
            "pattern": self.pattern,
            "risk_score": self.severity,
            "description": self.description,
            "evidence": evidence,
        }

    @staticmethod
    def _results(
        rule_id: str, rows: list[tuple[str, dict[str, Any]]]
    ) -> pd.DataFrame:
        """Build a result frame from ``(record_id, evidence)`` pairs."""
        return pd.DataFrame(
            {
                "record_id": [record_id for record_id, _ in rows],
                "rule_id": [rule_id] * len(rows),
                "evidence_json": [json.dumps(evidence) for _, evidence in rows],
            },
            columns=RESULT_COLUMNS,
        )
