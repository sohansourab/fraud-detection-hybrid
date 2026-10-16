"""Run the tool loop for one flagged record and return a verified draft."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fraud.agent.llm import MAX_REVISIONS, LLMClient
from fraud.agent.tools import MAX_TOOL_CALLS, Case, Evidence, ToolError, Toolbox
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
    tool_call_log: list[dict[str, Any]] = field(default_factory=list)
    revisions_accepted: int = 0
    revision_rejected: bool = False

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
            "revisions_accepted": self.revisions_accepted,
            "revision_rejected": self.revision_rejected,
            "tool_calls": self.tool_calls,
            "tool_call_log": self.tool_call_log,
            "status": self.status,
            "mode": self.mode,
            "error": self.error,
        }


def _is_better(candidate: Verification, best: Verification) -> bool:
    """A revision wins on fewer unsupported sentences, or an equal count and a
    lower unsupported rate (i.e. more supported content overall)."""
    if candidate.unsupported != best.unsupported:
        return candidate.unsupported < best.unsupported
    return candidate.rate < best.rate


def _run_plan(
    requested: list[dict[str, Any]], toolbox: Toolbox
) -> tuple[list[dict[str, Any]], str | None]:
    """Execute the requested calls, recording every one (even capped/malformed).

    At most :data:`MAX_TOOL_CALLS` calls are executed; later calls are recorded
    with ``capped`` set and never run. A call the client marked ``malformed``
    is recorded as-is. Any other tool error stops the loop, as before.
    """
    log: list[dict[str, Any]] = []
    error: str | None = None
    executed = 0
    for call in requested:
        tool = call.get("tool")
        arguments = call.get("arguments")
        malformed = call.get("malformed")
        if malformed:
            log.append(
                {
                    "tool": tool,
                    "arguments": arguments,
                    "executed": False,
                    "capped": False,
                    "malformed": malformed,
                }
            )
            continue
        if executed >= MAX_TOOL_CALLS:
            log.append(
                {
                    "tool": tool,
                    "arguments": arguments,
                    "executed": False,
                    "capped": True,
                    "malformed": None,
                }
            )
            continue
        try:
            toolbox.call(tool, arguments)
        except ToolError as exc:
            error = str(exc)
            log.append(
                {
                    "tool": tool,
                    "arguments": arguments,
                    "executed": False,
                    "capped": False,
                    "malformed": None,
                    "error": str(exc),
                }
            )
            break
        executed += 1
        log.append(
            {
                "tool": tool,
                "arguments": arguments,
                "executed": True,
                "capped": False,
                "malformed": None,
            }
        )
    return log, error


def investigate(case: Case, client: LLMClient, toolbox: Toolbox) -> CaseResult:
    """Plan tool calls, draft, then verify and revise (at most two revisions).

    The "before" rate is measured on the drafter's *first* output, so that
    verification is kept separate from the revision loop. A revision is kept
    only if it has fewer unsupported sentences (or the same count at a lower
    rate); otherwise the best draft so far is kept and the case is marked
    ``revision_rejected``.
    """
    tool_call_log, error = _run_plan(client.plan(case), toolbox)

    evidence = toolbox.evidence
    draft_first = client.draft(case, evidence)
    verification_first = verify_draft(draft_first, evidence)

    best_draft = draft_first
    best_verification = verification_first
    revisions = 0
    revisions_accepted = 0
    revisions_rejected = 0
    while not best_verification.verdict and revisions < MAX_REVISIONS:
        candidate = client.revise(case, best_draft, best_verification, evidence)
        candidate_verification = verify_draft(candidate, evidence)
        revisions += 1
        if _is_better(candidate_verification, best_verification):
            best_draft = candidate
            best_verification = candidate_verification
            revisions_accepted += 1
        else:
            revisions_rejected += 1
            break

    status = "verified" if best_verification.verdict else "needs_human"
    return CaseResult(
        record_id=case.record_id,
        domain=case.domain,
        rule_ids=case.rule_ids,
        evidence=evidence,
        draft_first=draft_first,
        draft_final=best_draft,
        verification_first=verification_first,
        verification=best_verification,
        revisions=revisions,
        revisions_accepted=revisions_accepted,
        revision_rejected=revisions_rejected > 0,
        tool_calls=toolbox.calls,
        tool_call_log=tool_call_log,
        status=status,
        mode=client.mode,
        error=error,
    )
