"""Read-only tools the investigator agent may call on a flagged record.

Every tool answers from the scanner's input tables (``beneficiaries`` /
``mgnrega`` / ``pmjay``) and the rule registry only. Ground-truth labels are
never loaded here.

Each call appends one :class:`Evidence` item with a sequential id (``E1``,
``E2``, ...). A per-case counter caps the number of tool calls at
:data:`MAX_TOOL_CALLS`; the ``(cap + 1)``-th call raises :class:`ToolError`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from fraud.config import get_config
from fraud.rules import get_rules

#: Repository root, used to resolve the relative paths in ``configs/default.yaml``.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Maximum number of tool calls allowed for one case.
MAX_TOOL_CALLS = 6

#: JSON schemas for the four tools (also used to validate calls).
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_record": {
        "name": "get_record",
        "description": "Return the input-table fields recorded for a flagged record.",
        "parameters": {
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "required": ["record_id"],
        },
    },
    "get_neighbors": {
        "name": "get_neighbors",
        "description": (
            "List other records sharing the record's beneficiary id, job card "
            "or mobile number."
        ),
        "parameters": {
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "required": ["record_id"],
        },
    },
    "explain_rule": {
        "name": "explain_rule",
        "description": "Return a rule's name, domain, severity and description.",
        "parameters": {
            "type": "object",
            "properties": {"rule_id": {"type": "string"}},
            "required": ["rule_id"],
        },
    },
    "run_rule": {
        "name": "run_rule",
        "description": (
            "Report whether one rule flags one record, with the rule's evidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "string"},
                "record_id": {"type": "string"},
            },
            "required": ["rule_id", "record_id"],
        },
    },
}

#: Column names that would leak ground truth if a table ever carried them.
_LABEL_COLUMNS = {
    "is_fraud",
    "fraud_type",
    "injected_rule_id",
    "split",
    "label",
    "labels",
}

_DOMAIN_ORDER = ("Civil Registry", "MGNREGA Labor", "PM-JAY Medical")
_DOMAIN_TABLES = {
    "Civil Registry": "beneficiaries",
    "MGNREGA Labor": "mgnrega",
    "PM-JAY Medical": "pmjay",
}
_CROSS_DOMAIN = "Cross-Domain"
_MAX_NEIGHBORS = 20


class ToolError(RuntimeError):
    """Raised when a tool cannot answer (bad id, unknown rule, cap reached)."""


@dataclass
class Evidence:
    """One grounded fact returned by a tool."""

    id: str
    tool: str
    text: str
    arguments: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "text": self.text,
            "arguments": self.arguments,
            "data": self.data,
        }


@dataclass(frozen=True)
class CaseFlag:
    """One rule that flagged a record (metadata only, no evidence)."""

    rule_id: str
    name: str
    domain: str
    severity: int
    description: str


@dataclass
class Case:
    """A flagged record to investigate."""

    record_id: str
    domain: str
    flags: list[CaseFlag] = field(default_factory=list)

    @property
    def rule_ids(self) -> list[str]:
        return [flag.rule_id for flag in self.flags]


# ---------------------------------------------------------------------------
# Loading and scanning
# ---------------------------------------------------------------------------

def load_tables(cfg: Any | None = None) -> dict[str, pd.DataFrame]:
    """Load the scanner's three input tables from the configured paths."""
    cfg = cfg or get_config()
    tables: dict[str, pd.DataFrame] = {}
    for name in ("beneficiaries", "mgnrega", "pmjay"):
        path = Path(getattr(cfg.paths, name))
        if not path.is_absolute():
            path = REPO_ROOT / path
        tables[name] = pd.read_csv(path)
    return tables


def scan_flags(
    tables: dict[str, pd.DataFrame],
    rules: list[Any] | None = None,
    cfg: Any | None = None,
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Run every rule and return ``{record_id: [(rule_id, evidence), ...]}``.

    Mirrors ``audit_scanner`` (per-domain rules first, then the cross-domain
    rule over the already flagged records) without printing or writing anything.
    """
    rules = list(rules) if rules is not None else get_rules()
    cfg = cfg or get_config()
    flags: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    domain_of: dict[str, str] = {}

    for domain in _DOMAIN_ORDER:
        if _DOMAIN_TABLES[domain] not in tables:
            continue
        for rule in rules:
            if rule.domain != domain:
                continue
            result = rule.evaluate(tables, cfg)
            for record_id, payload in zip(
                result["record_id"], result["evidence_json"], strict=True
            ):
                record_id = str(record_id)
                flags.setdefault(record_id, []).append((rule.id, json.loads(payload)))
                domain_of[record_id] = domain

    cross_rules = [rule for rule in rules if rule.domain == _CROSS_DOMAIN]
    if cross_rules and flags:
        scoped = dict(tables)
        scoped["flagged_records"] = pd.DataFrame(
            [{"record_id": rid, "domain": domain_of[rid]} for rid in flags],
            columns=["record_id", "domain"],
        )
        for rule in cross_rules:
            result = rule.evaluate(scoped, cfg)
            for record_id, payload in zip(
                result["record_id"], result["evidence_json"], strict=True
            ):
                record_id = str(record_id)
                entries = flags.get(record_id)
                if entries is None:
                    continue
                if any(existing == rule.id for existing, _ in entries):
                    continue
                entries.append((rule.id, json.loads(payload)))

    return flags


def build_domain_map(tables: dict[str, pd.DataFrame]) -> dict[str, str]:
    """Map every input record id to its domain."""
    domain_map: dict[str, str] = {}
    for id_column, domain in (
        ("BeneficiaryID", "Civil Registry"),
        ("TransactionID", "MGNREGA Labor"),
        ("ClaimID", "PM-JAY Medical"),
    ):
        frame = tables.get(_DOMAIN_TABLES[domain])
        if frame is None or id_column not in frame.columns:
            continue
        for value in frame[id_column].astype(str):
            domain_map.setdefault(value, domain)
    return domain_map


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _clean(value: Any) -> str | None:
    """Return a stripped string, or ``None`` for missing/blank values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "nat"}:
        return None
    return text


def _render(value: Any) -> str:
    """Render a cell as text (whole floats as integers)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _is_missing(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _records(frame: pd.DataFrame | None, id_column: str) -> dict[str, dict[str, Any]]:
    """Index a frame by its id column as plain row dicts."""
    if frame is None or getattr(frame, "empty", True) or id_column not in frame.columns:
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for row in frame.to_dict("records"):
        record_id = _clean(row.get(id_column))
        if record_id is not None:
            indexed[record_id] = row
    return indexed


# ---------------------------------------------------------------------------
# Toolbox
# ---------------------------------------------------------------------------

class Toolbox:
    """Per-case tool executor: enforces the cap and numbers the evidence."""

    def __init__(
        self,
        tables: dict[str, pd.DataFrame],
        rules: list[Any] | None = None,
        cfg: Any | None = None,
        scan: dict[str, list[tuple[str, dict[str, Any]]]] | None = None,
        cap: int = MAX_TOOL_CALLS,
    ) -> None:
        self._tables = tables
        self._rules = {
            rule.id: rule for rule in (rules if rules is not None else get_rules())
        }
        self._cfg = cfg or get_config()
        self._scan = (
            scan
            if scan is not None
            else scan_flags(tables, list(self._rules.values()), self._cfg)
        )
        self._cap = cap
        self._calls = 0
        self._evidence: list[Evidence] = []
        self._beneficiaries = _records(tables.get("beneficiaries"), "BeneficiaryID")
        self._mgnrega = _records(tables.get("mgnrega"), "TransactionID")
        self._pmjay = _records(tables.get("pmjay"), "ClaimID")
        self._job_card_to_ben: dict[str, str] = {}
        for record_id, row in self._beneficiaries.items():
            job_card = _clean(row.get("JobCardID"))
            if job_card is not None:
                self._job_card_to_ben.setdefault(job_card, record_id)

    # -- state -------------------------------------------------------------

    @property
    def calls(self) -> int:
        """Number of tool calls charged so far."""
        return self._calls

    @property
    def evidence(self) -> list[Evidence]:
        """Evidence items collected so far, in call order."""
        return list(self._evidence)

    @property
    def scan(self) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        return self._scan

    def _charge(self) -> None:
        self._calls += 1
        if self._calls > self._cap:
            raise ToolError(f"tool call cap of {self._cap} exceeded")

    def _emit(
        self,
        tool: str,
        arguments: dict[str, Any],
        text: str,
        data: dict[str, Any] | None = None,
    ) -> list[Evidence]:
        item = Evidence(
            id=f"E{len(self._evidence) + 1}",
            tool=tool,
            text=text,
            arguments=dict(arguments),
            data=dict(data or {}),
        )
        self._evidence.append(item)
        return [item]

    # -- dispatch ----------------------------------------------------------

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> list[Evidence]:
        """Validate and run one tool by name (the model-facing entry point)."""
        if name not in TOOL_SCHEMAS:
            raise ToolError(f"unknown tool: {name}")
        arguments = dict(arguments or {})
        required = TOOL_SCHEMAS[name]["parameters"].get("required", [])
        missing = [key for key in required if key not in arguments]
        if missing:
            raise ToolError(f"{name}: missing arguments {missing}")
        handler = getattr(self, name, None)
        if handler is None:
            raise ToolError(f"unknown tool: {name}")
        return handler(**arguments)

    # -- tools -------------------------------------------------------------

    def get_record(self, record_id: str) -> list[Evidence]:
        """Return the input-table fields recorded for ``record_id``."""
        self._charge()
        record_id = str(record_id)
        row, domain = self._lookup(record_id)
        fields = {
            key: value
            for key, value in row.items()
            if key.lower() not in _LABEL_COLUMNS and not _is_missing(value)
        }
        rendered = " | ".join(f"{key}={_render(value)}" for key, value in fields.items())
        text = f"record {record_id} | domain={domain} | {rendered}"
        data = {
            "record": {key: _render(value) for key, value in fields.items()},
            "domain": domain,
        }
        return self._emit("get_record", {"record_id": record_id}, text, data)

    def get_neighbors(self, record_id: str) -> list[Evidence]:
        """List other records sharing a beneficiary id, job card or mobile."""
        self._charge()
        record_id = str(record_id)
        self._lookup(record_id)
        context = self._context(record_id)
        found: dict[str, set[str]] = {}

        def add(other_id: Any, key: str) -> None:
            other = _clean(other_id)
            if other is None or other == record_id:
                return
            found.setdefault(other, set()).add(key)

        beneficiary_id = context["beneficiary_id"]
        job_cards = context["job_cards"]
        mobile = context["mobile"]

        if beneficiary_id is not None:
            for other_id, row in self._pmjay.items():
                if _clean(row.get("BeneficiaryID")) == beneficiary_id:
                    add(other_id, "beneficiary_id")
        for other_id, row in self._mgnrega.items():
            if _clean(row.get("JobCardID")) in job_cards:
                add(other_id, "job_card")
        for other_id, row in self._beneficiaries.items():
            if _clean(row.get("JobCardID")) in job_cards:
                add(other_id, "job_card")
            if mobile is not None and _clean(row.get("MobileNumber")) == mobile:
                add(other_id, "mobile")

        neighbors = [
            {"record_id": other, "shares": sorted(keys)}
            for other, keys in sorted(found.items())
        ][:_MAX_NEIGHBORS]
        if neighbors:
            detail = "; ".join(
                f"{item['record_id']} shares {', '.join(item['shares'])}"
                for item in neighbors
            )
            text = f"{len(neighbors)} neighbor record(s) for {record_id}: {detail}"
        else:
            text = f"0 neighbor record(s) for {record_id}"
        data = {"count": len(neighbors), "neighbors": neighbors}
        return self._emit("get_neighbors", {"record_id": record_id}, text, data)

    def explain_rule(self, rule_id: str) -> list[Evidence]:
        """Return one rule's name, domain, severity and description."""
        self._charge()
        rule_id = str(rule_id)
        rule = self._rules.get(rule_id)
        if rule is None:
            raise ToolError(f"unknown rule: {rule_id}")
        text = (
            f"rule {rule_id} | name={rule.name} | domain={rule.domain} "
            f"| severity={rule.severity} | description={rule.description}"
        )
        data = {
            "rule_id": rule_id,
            "name": rule.name,
            "domain": rule.domain,
            "severity": rule.severity,
            "description": rule.description,
        }
        return self._emit("explain_rule", {"rule_id": rule_id}, text, data)

    def run_rule(self, rule_id: str, record_id: str) -> list[Evidence]:
        """Report whether ``rule_id`` flags ``record_id``, with its evidence."""
        self._charge()
        rule_id = str(rule_id)
        record_id = str(record_id)
        rule = self._rules.get(rule_id)
        if rule is None:
            raise ToolError(f"unknown rule: {rule_id}")
        evidence = dict(self._scan.get(record_id, [])).get(rule_id)
        flagged = evidence is not None
        if flagged:
            payload = json.dumps(evidence, sort_keys=True)
            text = (
                f"rule {rule_id} ({rule.name}) flags record {record_id} "
                f"| evidence={payload}"
            )
        else:
            text = f"rule {rule_id} ({rule.name}) does not flag record {record_id}"
        data = {"flagged": flagged, "evidence": evidence}
        return self._emit(
            "run_rule", {"rule_id": rule_id, "record_id": record_id}, text, data
        )

    # -- internals ---------------------------------------------------------

    def _lookup(self, record_id: str) -> tuple[dict[str, Any], str]:
        if record_id in self._beneficiaries:
            return self._beneficiaries[record_id], "Civil Registry"
        if record_id in self._mgnrega:
            return self._mgnrega[record_id], "MGNREGA Labor"
        if record_id in self._pmjay:
            return self._pmjay[record_id], "PM-JAY Medical"
        raise ToolError(f"no input row for record {record_id}")

    def _context(self, record_id: str) -> dict[str, Any]:
        """Resolve a record to its beneficiary id, job card(s) and mobile."""
        beneficiary_id: str | None = None
        job_card: str | None = None
        mobile: str | None = None

        if record_id in self._beneficiaries:
            row = self._beneficiaries[record_id]
            beneficiary_id = record_id
            job_card = _clean(row.get("JobCardID"))
            mobile = _clean(row.get("MobileNumber"))
        elif record_id in self._mgnrega:
            job_card = _clean(self._mgnrega[record_id].get("JobCardID"))
            if job_card is not None:
                beneficiary_id = self._job_card_to_ben.get(job_card)
        elif record_id in self._pmjay:
            beneficiary_id = _clean(self._pmjay[record_id].get("BeneficiaryID"))

        if beneficiary_id is not None and beneficiary_id in self._beneficiaries:
            beneficiary_row = self._beneficiaries[beneficiary_id]
            mobile = mobile or _clean(beneficiary_row.get("MobileNumber"))
            job_card = job_card or _clean(beneficiary_row.get("JobCardID"))

        job_cards: set[str] = set()
        if beneficiary_id is not None:
            for row in self._beneficiaries.values():
                if _clean(row.get("BeneficiaryID")) == beneficiary_id:
                    candidate = _clean(row.get("JobCardID"))
                    if candidate is not None:
                        job_cards.add(candidate)
        if job_card is not None:
            job_cards.add(job_card)

        return {
            "beneficiary_id": beneficiary_id,
            "job_card": job_card,
            "mobile": mobile,
            "job_cards": job_cards,
        }
