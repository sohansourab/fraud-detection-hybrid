"""Run the tool loop for one flagged record and return a verified draft."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fraud.agent.llm import MAX_REVISIONS, LLMClient
from fraud.agent.tools import Case, Evidence, ToolError, Toolbox
from fraud.agent.verifier import Verification, verify_draft


@dataclass
class CaseResult:
    """Everything one investigation produced."""

    record_id: str
    domain: str
    rule_ids: list[str]
    evidence: list[Evidence]
    draft_first: str
    draft_final: str
    verification_first: Verification
    verification: Verification
    revisions: int
    tool_calls: int
    status: str
    mode: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "domain": self.domain,
            "rule_ids": self.rule_ids,
            "evidence": [item.to_dict() for item in self.evidence],
            "draft_first": self.draft_first,
            "draft_final": self.draft_final,
            "verification_first": self.verification_first.to_dict(),
            "verification": self.verification.to_dict(),
            "revisions": self.revisions,
            "tool_calls": self.tool_calls,
            "status": self.status,
            "mode": self.mode,
            "error": self.error,
        }


def investigate(case: Case, client: LLMClient, toolbox: Toolbox) -> CaseResult:
    """Plan tool calls, draft, then verify and revise (at most two revisions).

    The "before" rate is measured on the drafter's *first* output, so that
    verification is kept separate from the revision loop.
    """
    error: str | None = None
    for call in client.plan(case):
        try:
            toolbox.call(call["tool"], call["arguments"])
        except ToolError as exc:
            error = str(exc)
            break

    evidence = toolbox.evidence
    draft_first = client.draft(case, evidence)
    verification_first = verify_draft(draft_first, evidence)

    draft_final = draft_first
    verification = verification_first
    revisions = 0
    while not verification.verdict and revisions < MAX_REVISIONS:
        draft_final = client.revise(case, draft_final, verification, evidence)
        verification = verify_draft(draft_final, evidence)
        revisions += 1

    status = "verified" if verification.verdict else "needs_human"
    return CaseResult(
        record_id=case.record_id,
        domain=case.domain,
        rule_ids=case.rule_ids,
        evidence=evidence,
        draft_first=draft_first,
        draft_final=draft_final,
        verification_first=verification_first,
        verification=verification,
        revisions=revisions,
        tool_calls=toolbox.calls,
        status=status,
        mode=client.mode,
        error=error,
    )
