"""Deterministic verifier for a draft.

A sentence passes only if it (a) carries at least one ``[E#]`` citation that
exists in the evidence list, and (b) every number in the sentence appears in
the text of the cited evidence (numbers inside citations are ignored, and
thousands separators are removed before comparison).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from fraud.agent.tools import Evidence

_EVIDENCE_RE = re.compile(r"\[(E\d+)\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences on line breaks and ``.``/``!``/``?`` ends."""
    sentences: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-*").strip()
        if not line:
            continue
        sentences.extend(part.strip() for part in _SENTENCE_SPLIT.split(line) if part.strip())
    return sentences


def evidence_ids(text: str) -> list[str]:
    """Every ``[E#]`` citation in ``text``, in order."""
    return _EVIDENCE_RE.findall(text or "")


def numbers(text: str) -> set[str]:
    """Numeric tokens in ``text``, ignoring citations and thousands separators."""
    without_citations = _EVIDENCE_RE.sub(" ", text or "")
    return set(_NUMBER_RE.findall(without_citations.replace(",", "")))


@dataclass
class SentenceResult:
    """The verdict for one sentence."""

    sentence: str
    evidence_ids: list[str]
    passed: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sentence": self.sentence,
            "evidence_ids": self.evidence_ids,
            "passed": self.passed,
            "reasons": self.reasons,
        }


@dataclass
class Verification:
    """The verdict for a whole draft."""

    sentences: list[SentenceResult]
    verdict: bool

    @property
    def unsupported(self) -> int:
        """Number of sentences that failed."""
        return sum(1 for sentence in self.sentences if not sentence.passed)

    @property
    def total(self) -> int:
        return len(self.sentences)

    def critique(self) -> str:
        """A repair note listing every rejected sentence and why."""
        if self.verdict:
            return ""
        lines = ["Fix these sentences:"]
        for sentence in self.sentences:
            if not sentence.passed:
                lines.append(f'- "{sentence.sentence}" -> ' + "; ".join(sentence.reasons))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "total": self.total,
            "unsupported": self.unsupported,
            "sentences": [sentence.to_dict() for sentence in self.sentences],
        }


def verify_sentence(
    sentence: str, evidence_by_id: dict[str, Evidence]
) -> SentenceResult:
    """Check one sentence against the evidence it cites."""
    ids = evidence_ids(sentence)
    reasons: list[str] = []
    cited = [item for item in ids if item in evidence_by_id]
    if not cited:
        reasons.append("no [E#] citation that exists in the evidence list")

    allowed: set[str] = set()
    for evidence_id in cited:
        allowed |= numbers(evidence_by_id[evidence_id].text)
    missing = sorted(token for token in numbers(sentence) if token not in allowed)
    if missing:
        reasons.append(f"number(s) not in the cited evidence: {', '.join(missing)}")

    return SentenceResult(
        sentence=sentence,
        evidence_ids=ids,
        passed=not reasons,
        reasons=reasons,
    )


def verify_draft(text: str, evidence: list[Evidence]) -> Verification:
    """Verify every sentence of ``text`` against ``evidence``."""
    by_id = {item.id: item for item in evidence}
    sentences = [verify_sentence(sentence, by_id) for sentence in split_sentences(text)]
    return Verification(
        sentences=sentences,
        verdict=all(sentence.passed for sentence in sentences),
    )
