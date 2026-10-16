"""Agent-layer tests: tools, offline LLM, verifier, guardrails, cap."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud.agent.llm import LLMClient, load_llm_config  # noqa: E402
from fraud.agent.tools import (  # noqa: E402
    MAX_TOOL_CALLS,
    TOOL_SCHEMAS,
    Case,
    CaseFlag,
    ToolError,
    Toolbox,
)
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


def _tables(name: str = "Asha Devi") -> dict[str, pd.DataFrame]:
    return {
        "beneficiaries": pd.DataFrame(
            [
                {
                    "BeneficiaryID": "BEN_1",
                    "Name": name,
                    "MobileNumber": "9000000001",
                    "JobCardID": "JC_1",
                    "FamilyID": "FAM_1",
                },
                {
                    "BeneficiaryID": "BEN_2",
                    "Name": "Bina Das",
                    "MobileNumber": "9000000001",
                    "JobCardID": "JC_2",
                    "FamilyID": "FAM_2",
                },
            ]
        ),
        "mgnrega": pd.DataFrame([{"TransactionID": "TXN_1", "JobCardID": "JC_1"}]),
        "pmjay": pd.DataFrame([{"ClaimID": "CLM_1", "BeneficiaryID": "BEN_1"}]),
    }


def _scan() -> dict:
    return {"BEN_1": [("RULE_TEST", {"shared_by": 2})]}


def _toolbox(tables: dict[str, pd.DataFrame] | None = None) -> Toolbox:
    return Toolbox(
        tables if tables is not None else _tables(),
        rules=[_FakeRule()],
        scan=_scan(),
        cfg=get_config(),
    )


def _case() -> Case:
    return Case(record_id="BEN_1", domain="Civil Registry", flags=[FAKE_FLAG])


def _offline_client() -> LLMClient:
    return LLMClient(load_llm_config(env={}))


def test_tool_schemas_cover_four_tools() -> None:
    assert set(TOOL_SCHEMAS) == {
        "get_record",
        "get_neighbors",
        "explain_rule",
        "run_rule",
    }


def test_get_record_excludes_label_columns() -> None:
    tables = _tables()
    tables["beneficiaries"]["is_fraud"] = 1
    evidence = _toolbox(tables).get_record("BEN_1")
    assert "is_fraud" not in evidence[0].text


def test_tool_call_cap_enforced() -> None:
    toolbox = _toolbox()
    for _ in range(MAX_TOOL_CALLS):
        toolbox.get_record("BEN_1")
    assert toolbox.calls == MAX_TOOL_CALLS
    try:
        toolbox.get_record("BEN_1")
    except ToolError:
        pass
    else:  # pragma: no cover - the cap must reject the extra call
        raise AssertionError("the 7th tool call should be rejected")


def test_offline_mode_makes_no_network_calls(monkeypatch) -> None:
    import socket

    def _boom(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("offline mode attempted a network call")

    monkeypatch.setattr(socket, "socket", _boom)

    client = _offline_client()
    assert client.offline is True
    assert client.mode == "offline"

    toolbox = _toolbox()
    for call in client.plan(_case()):
        toolbox.call(call["tool"], call["arguments"])
    draft = client.draft(_case(), toolbox.evidence)
    assert "flagged for review" in draft


def test_offline_plan_is_fixed_and_within_cap() -> None:
    plan = _offline_client().plan(_case())
    assert len(plan) <= MAX_TOOL_CALLS
    assert plan[0] == {"tool": "get_record", "arguments": {"record_id": "BEN_1"}}
    assert plan[-1]["tool"] == "get_neighbors"
