"""AGENT-FIX tests: LLM tool choice, revision acceptance, citation parser."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud.agent.investigator import _is_better, investigate  # noqa: E402
from fraud.agent.llm import (  # noqa: E402
    LLMClient,
    load_llm_config,
    parse_tool_calls,
)
from fraud.agent.tools import (  # noqa: E402
    MAX_TOOL_CALLS,
    Case,
    CaseFlag,
    Evidence,
    Toolbox,
)
from fraud.agent.verifier import evidence_ids, verify_draft  # noqa: E402
from fraud.config import get_config  # noqa: E402
from fraud.rules.base import Rule  # noqa: E402

FAKE_FLAG = CaseFlag(
    rule_id="RULE_TEST",
    name="Fake Rule",
    domain="Civil Registry",
    severity=25,
    description="Test-only rule",
)


class _FakeRule(Rule):
    """A rule that is never evaluated (the tool tests supply a scan directly)."""

    id = "RULE_TEST"
    domain = "Civil Registry"
    name = "Fake Rule"
    pattern = "Test"
    description = "Test-only rule"
    severity = 25

    def evaluate(self, tables, cfg):  # pragma: no cover - never called here
        raise NotImplementedError("_FakeRule is never evaluated")


def _tables() -> dict[str, pd.DataFrame]:
    return {
        "beneficiaries": pd.DataFrame(
            [
                {
                    "BeneficiaryID": "BEN_1",
                    "Name": "Asha Devi",
                    "MobileNumber": "9000000001",
                    "JobCardID": "JC_1",
                    "FamilyID": "FAM_1",
                }
            ]
        ),
        "mgnrega": pd.DataFrame([{"TransactionID": "TXN_1", "JobCardID": "JC_1"}]),
        "pmjay": pd.DataFrame([{"ClaimID": "CLM_1", "BeneficiaryID": "BEN_1"}]),
    }


def _toolbox() -> Toolbox:
    return Toolbox(
        _tables(),
        rules=[_FakeRule()],
        scan={"BEN_1": [("RULE_TEST", {"shared_by": 2})]},
        cfg=get_config(),
    )


def _case() -> Case:
    return Case(record_id="BEN_1", domain="Civil Registry", flags=[FAKE_FLAG])


def _offline_client() -> LLMClient:
    return LLMClient(load_llm_config(env={}))


class _ScriptedClient:
    """A deterministic stand-in for :class:`LLMClient`."""

    def __init__(self, calls: list[dict], drafts: list[str], mode: str = "llm") -> None:
        self._calls = calls
        self._drafts = list(drafts)
        self._next = 1
        self.mode = mode

    def plan(self, case: Case) -> list[dict]:
        return [dict(call) for call in self._calls]

    def draft(self, case: Case, evidence: list[Evidence]) -> str:
        return self._drafts[0]

    def revise(self, case, draft, verification, evidence) -> str:
        text = self._drafts[self._next]
        self._next += 1
        return text


class _StubToolbox:
    """A toolbox that returns a fixed evidence list and never calls a tool."""

    def __init__(self, evidence: list[Evidence]) -> None:
        self._evidence = evidence
        self._calls = 0

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def evidence(self) -> list[Evidence]:
        return list(self._evidence)

    def call(self, name, arguments=None):  # pragma: no cover - plan is empty
        self._calls += 1
        return list(self._evidence)


# ---------------------------------------------------------------------------
# Step 5: LLM tool choice, cap and malformed calls
# ---------------------------------------------------------------------------

def test_tool_call_cap_records_capped_calls() -> None:
    calls = [{"tool": "get_record", "arguments": {"record_id": "BEN_1"}}] * 8
    client = _ScriptedClient(calls, ["The record was flagged for review [E1]."])
    result = investigate(_case(), client, _toolbox())
    assert result.tool_calls == MAX_TOOL_CALLS
    assert len(result.tool_call_log) == 8
    assert sum(1 for entry in result.tool_call_log if entry["executed"]) == MAX_TOOL_CALLS
    capped = [entry for entry in result.tool_call_log if entry["capped"]]
    assert len(capped) == 2
    assert all(entry["executed"] is False for entry in capped)


def test_bad_json_arguments_are_recorded_not_dropped() -> None:
    message = {
        "tool_calls": [
            {"function": {"name": "get_record", "arguments": "{not valid json"}}
        ]
    }
    planned = parse_tool_calls(message)
    assert planned[0]["tool"] == "get_record"
    assert planned[0]["malformed"]

    client = _ScriptedClient(
        planned,
        [
            "The record was flagged for review [E1].",
            "The record was flagged for review [E1].",
            "The record was flagged for review [E1].",
        ],
    )
    result = investigate(_case(), client, _toolbox())
    assert len(result.tool_call_log) == 1
    assert result.tool_call_log[0]["malformed"]
    assert result.tool_call_log[0]["executed"] is False
    assert result.tool_calls == 0


def test_unknown_tool_name_is_malformed() -> None:
    message = {
        "tool_calls": [{"function": {"name": "delete_all", "arguments": "{}"}}]
    }
    planned = parse_tool_calls(message)
    assert "unknown tool" in planned[0]["malformed"]


# ---------------------------------------------------------------------------
# Step 6: revision acceptance
# ---------------------------------------------------------------------------

def test_revision_rejected_when_unsupported_increases() -> None:
    evidence = [Evidence(id="E1", tool="get_record", text="shared_by=2")]
    drafts = [
        "The count is 99 [E1].",
        "The count is 88 [E1]. The count is 77 [E1].",
    ]
    client = _ScriptedClient([], drafts)
    result = investigate(_case(), client, _StubToolbox(evidence))
    assert result.revision_rejected is True
    assert result.revisions == 1
    assert result.revisions_accepted == 0
    assert result.draft_final == drafts[0]
    assert result.verification.unsupported == 1


def test_revision_accepted_when_unsupported_drops() -> None:
    evidence = [Evidence(id="E1", tool="get_record", text="shared_by=2")]
    drafts = ["The count is 99 [E1].", "The count is 2 [E1]."]
    client = _ScriptedClient([], drafts)
    result = investigate(_case(), client, _StubToolbox(evidence))
    assert result.revision_rejected is False
    assert result.revisions == 1
    assert result.revisions_accepted == 1
    assert result.draft_final == drafts[1]
    assert result.verification.verdict is True


def test_revision_accepted_on_equal_count_lower_rate() -> None:
    evidence = [Evidence(id="E1", tool="get_record", text="shared_by=2")]
    best = verify_draft("The count is 99 [E1]. The count is 2 [E1].", evidence)
    candidate = verify_draft(
        "The count is 2 [E1]. The count is 2 [E1]. "
        "The count is 2 [E1]. The count is 99 [E1].",
        evidence,
    )
    assert best.unsupported == candidate.unsupported == 1
    assert candidate.rate < best.rate
    assert _is_better(candidate, best) is True
    assert _is_better(best, candidate) is False


# ---------------------------------------------------------------------------
# Step 7: citation parser
# ---------------------------------------------------------------------------

def test_parser_accepts_multi_citations() -> None:
    evidence = [
        Evidence(id="E2", tool="get_record", text="amount=5"),
        Evidence(id="E4", tool="get_record", text="amount=7"),
    ]
    for text in (
        "The amount is 5 [E2, E4].",
        "The amount is 5 [E2][E4].",
        "The amount is 5 [E2] [E4].",
    ):
        assert evidence_ids(text) == ["E2", "E4"], text
        assert verify_draft(text, evidence).verdict is True, text


def test_parser_rejects_id_not_in_evidence() -> None:
    evidence = [Evidence(id="E1", tool="get_record", text="amount=5")]
    assert verify_draft("The amount is 5 [E9].", evidence).verdict is False
    assert verify_draft("The amount is 5 [E1, E9].", evidence).verdict is False


# ---------------------------------------------------------------------------
# Offline guardrail
# ---------------------------------------------------------------------------

def test_offline_mode_makes_zero_network_calls(monkeypatch) -> None:
    import socket

    def _boom(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("offline mode attempted a network call")

    monkeypatch.setattr(socket, "socket", _boom)

    client = _offline_client()
    assert client.offline is True
    result = investigate(_case(), client, _toolbox())
    assert result.status == "verified"
    assert result.mode == "offline"
