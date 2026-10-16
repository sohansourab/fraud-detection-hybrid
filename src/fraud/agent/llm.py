"""OpenAI-compatible client with a deterministic OFFLINE fallback.

``LLM_BASE_URL``, ``LLM_API_KEY`` and ``LLM_MODEL`` are read from the
environment. When ``LLM_API_KEY`` is unset the client runs in OFFLINE mode: it
uses a fixed tool plan and template drafts, and makes **zero** network calls.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fraud.agent.tools import MAX_TOOL_CALLS, Case, Evidence

if TYPE_CHECKING:
    from fraud.agent.verifier import Verification

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

#: The drafter may revise at most this many times before a case is escalated.
MAX_REVISIONS = 2

SYSTEM_PROMPT = (
    "You are an auditor's assistant writing a short review note about one "
    "flagged record. Say 'flagged for review'; never say 'fraud', 'guilty' or "
    "'criminal'. Every factual sentence must end with the id of the evidence "
    "item it uses, for example [E1]. Only state facts that appear in the cited "
    "evidence."
)


@dataclass(frozen=True)
class LLMConfig:
    """Resolved LLM settings (``api_key`` is ``None`` in offline mode)."""

    base_url: str = DEFAULT_BASE_URL
    api_key: str | None = None
    model: str = DEFAULT_MODEL

    @property
    def offline(self) -> bool:
        return not self.api_key


def load_llm_config(env: dict[str, str] | None = None) -> LLMConfig:
    """Read the LLM settings from ``env`` (default: ``os.environ``)."""
    source = os.environ if env is None else env
    return LLMConfig(
        base_url=source.get("LLM_BASE_URL") or DEFAULT_BASE_URL,
        api_key=source.get("LLM_API_KEY") or None,
        model=source.get("LLM_MODEL") or DEFAULT_MODEL,
    )


class LLMClient:
    """Delegates drafting to a model, or to templates when offline."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or load_llm_config()

    @property
    def offline(self) -> bool:
        return self.config.offline

    @property
    def mode(self) -> str:
        return "offline" if self.offline else "llm"

    # -- planning ----------------------------------------------------------

    def plan(self, case: Case) -> list[dict[str, Any]]:
        """Return the tool calls to make for ``case`` (fixed and capped)."""
        calls: list[dict[str, Any]] = [
            {"tool": "get_record", "arguments": {"record_id": case.record_id}}
        ]
        for flag in case.flags[:2]:
            calls.append(
                {"tool": "explain_rule", "arguments": {"rule_id": flag.rule_id}}
            )
            calls.append(
                {
                    "tool": "run_rule",
                    "arguments": {"rule_id": flag.rule_id, "record_id": case.record_id},
                }
            )
        calls.append(
            {"tool": "get_neighbors", "arguments": {"record_id": case.record_id}}
        )
        return calls[:MAX_TOOL_CALLS]

    # -- drafting ----------------------------------------------------------

    def draft(self, case: Case, evidence: list[Evidence]) -> str:
        """Write the first draft for ``case`` from ``evidence``."""
        if self.offline:
            return offline_draft(case, evidence)
        return self._chat(self._draft_messages(case, evidence))

    def revise(
        self,
        case: Case,
        draft: str,
        verification: Verification,
        evidence: list[Evidence],
    ) -> str:
        """Rewrite ``draft`` after the verifier's critique."""
        if self.offline:
            return offline_draft(case, evidence)
        return self._chat(
            self._revise_messages(case, draft, verification, evidence)
        )

    # -- transport ---------------------------------------------------------

    def _chat(self, messages: list[dict[str, str]]) -> str:
        import urllib.request

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = json.dumps(
            {
                "model": self.config.model,
                "messages": messages,
                "temperature": 0,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(body["choices"][0]["message"]["content"]).strip()

    def _draft_messages(
        self, case: Case, evidence: list[Evidence]
    ) -> list[dict[str, str]]:
        lines = [
            f"Record: {case.record_id} (domain: {case.domain})",
            f"Rules that flagged it: {', '.join(case.rule_ids) or 'none'}",
            "Evidence:",
        ]
        lines.extend(f"[{item.id}] ({item.tool}) {item.text}" for item in evidence)
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ]

    def _revise_messages(
        self,
        case: Case,
        draft: str,
        verification: Verification,
        evidence: list[Evidence],
    ) -> list[dict[str, str]]:
        messages = self._draft_messages(case, evidence)
        messages.append({"role": "assistant", "content": draft})
        messages.append(
            {
                "role": "user",
                "content": "The verifier rejected this draft:\n"
                + verification.critique()
                + "\nRewrite it, citing only the evidence above.",
            }
        )
        return messages


# ---------------------------------------------------------------------------
# Offline templates (deterministic, grounded, no network)
# ---------------------------------------------------------------------------

def _by_tool(evidence: list[Evidence], tool: str) -> list[Evidence]:
    return [item for item in evidence if item.tool == tool]


def _fact_string(evidence: dict[str, Any] | None) -> str:
    """Render an evidence dict as ``key=value; key=value``."""
    if not isinstance(evidence, dict):
        return ""
    parts: list[str] = []
    for key in sorted(evidence):
        value = evidence[key]
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value)
        elif isinstance(value, dict):
            value = ", ".join(f"{k}={value[k]}" for k in sorted(value))
        parts.append(f"{key}={value}")
    return "; ".join(parts)


def offline_draft(case: Case, evidence: list[Evidence]) -> str:
    """Build a grounded draft by quoting the evidence it cites."""
    lines: list[str] = []

    records = _by_tool(evidence, "get_record")
    if records:
        lines.append(
            f"Record {case.record_id} was flagged for review in the "
            f"{case.domain} domain [{records[0].id}]."
        )

    explains = {
        item.arguments.get("rule_id"): item
        for item in _by_tool(evidence, "explain_rule")
    }
    for flag in case.flags[:2]:
        item = explains.get(flag.rule_id)
        if item is None:
            continue
        lines.append(
            f"Rule {flag.rule_id} ({flag.name}) flagged this record at severity "
            f"{flag.severity} [{item.id}]."
        )

    for item in _by_tool(evidence, "run_rule"):
        if item.data.get("flagged"):
            facts = _fact_string(item.data.get("evidence"))
            if facts:
                lines.append(f"The rule evidence reports {facts} [{item.id}].")
        else:
            rule_id = item.arguments.get("rule_id")
            lines.append(
                f"Rule {rule_id} does not flag this record [{item.id}]."
            )

    neighbors = _by_tool(evidence, "get_neighbors")
    if neighbors:
        count = neighbors[0].data.get("count", 0)
        lines.append(
            f"{count} other record(s) share an identifier with this record "
            f"[{neighbors[0].id}]."
        )

    if not lines:
        return (
            f"Record {case.record_id} was flagged for review in the "
            f"{case.domain} domain."
        )
    return "\n".join(lines)
