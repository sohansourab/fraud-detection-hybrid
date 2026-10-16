"""Entry point: ``python -m fraud.agent.run --n 20``.

Takes the ``--n`` flagged records with the most rules flagging them, runs the
investigator and the verifier on each, and writes ``reports/agent_cases.json``
and ``reports/agent_metrics.json``. The metric "before" is measured on the
drafter's first output, never on a corrected one.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fraud.agent.investigator import CaseResult, investigate  # noqa: E402
from fraud.agent.llm import LLMClient  # noqa: E402
from fraud.agent.tools import (  # noqa: E402
    Case,
    CaseFlag,
    Toolbox,
    build_domain_map,
    load_tables,
    scan_flags,
)
from fraud.config import get_config  # noqa: E402
from fraud.rules import get_rules  # noqa: E402

CASES_JSON = REPO_ROOT / "reports" / "agent_cases.json"
METRICS_JSON = REPO_ROOT / "reports" / "agent_metrics.json"

DISCLAIMER = (
    "Synthetic data, in-sample: cases come from the rule scan on the simulator's "
    "own injections, so these numbers are not a generalization estimate."
)

logger = logging.getLogger(__name__)


def build_cases(
    scan: dict[str, list[tuple[str, dict[str, Any]]]],
    rules_by_id: dict[str, Any],
    domain_map: dict[str, str],
    n: int,
) -> list[Case]:
    """Top ``n`` records ranked by flag count, ties broken by record id."""
    counts = {record_id: len(flags) for record_id, flags in scan.items()}
    ranked = sorted(counts, key=lambda record_id: (-counts[record_id], record_id))[:n]
    cases: list[Case] = []
    for record_id in ranked:
        flags = [
            CaseFlag(
                rule_id=rule_id,
                name=rules_by_id[rule_id].name,
                domain=rules_by_id[rule_id].domain,
                severity=rules_by_id[rule_id].severity,
                description=rules_by_id[rule_id].description,
            )
            for rule_id, _evidence in scan[record_id]
            if rule_id in rules_by_id
        ]
        cases.append(
            Case(record_id=record_id, domain=domain_map.get(record_id, "Unknown"), flags=flags)
        )
    return cases


def _rate(unsupported: int, total: int) -> float:
    return round(unsupported / total, 4) if total else 0.0


def _summary(values: list[int]) -> dict[str, Any]:
    return {
        "mean": round(sum(values) / len(values), 4) if values else 0.0,
        "max": max(values) if values else 0,
        "values": list(values),
    }


def compute_metrics(results: list[CaseResult], mode: str) -> dict[str, Any]:
    """Aggregate per-case results, keeping before/after rates separate."""
    before_total = sum(result.verification_first.total for result in results)
    before_bad = sum(result.verification_first.unsupported for result in results)
    after_total = sum(result.verification.total for result in results)
    after_bad = sum(result.verification.unsupported for result in results)
    statuses = Counter(result.status for result in results)
    return {
        "generated_by": "fraud.agent.run",
        "disclaimer": DISCLAIMER,
        "mode": mode,
        "n_cases": len(results),
        "unsupported_sentence_rate_before": _rate(before_bad, before_total),
        "unsupported_sentence_rate_after": _rate(after_bad, after_total),
        "sentences_before": before_total,
        "unsupported_before": before_bad,
        "sentences_after": after_total,
        "unsupported_after": after_bad,
        "tool_calls_per_case": _summary([result.tool_calls for result in results]),
        "revisions_per_case": _summary([result.revisions for result in results]),
        "status_counts": dict(sorted(statuses.items())),
    }


def run(
    n: int = 20,
    write: bool = True,
    client: LLMClient | None = None,
    tables: dict[str, Any] | None = None,
    rules: list[Any] | None = None,
    cfg: Any | None = None,
) -> dict[str, Any]:
    """Run the agent layer over the top ``n`` flagged records."""
    cfg = cfg or get_config()
    rules = get_rules() if rules is None else list(rules)
    tables = load_tables(cfg) if tables is None else tables
    scan = scan_flags(tables, rules, cfg)
    rules_by_id = {rule.id: rule for rule in rules}
    domain_map = build_domain_map(tables)
    cases = build_cases(scan, rules_by_id, domain_map, n)

    client = client or LLMClient()
    results = [
        investigate(case, client, Toolbox(tables, rules=rules, cfg=cfg, scan=scan))
        for case in cases
    ]
    metrics = compute_metrics(results, client.mode)

    if write:
        CASES_JSON.parent.mkdir(parents=True, exist_ok=True)
        CASES_JSON.write_text(
            json.dumps([result.to_dict() for result in results], indent=2),
            encoding="utf-8",
        )
        METRICS_JSON.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        logger.info("Wrote %s and %s", CASES_JSON, METRICS_JSON)

    return {"cases": [result.to_dict() for result in results], "metrics": metrics}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the agent layer over the top flagged records."
    )
    parser.add_argument("--n", type=int, default=20, help="number of cases")
    parser.add_argument("--no-write", action="store_true", help="do not write reports")
    args = parser.parse_args(argv)

    payload = run(n=args.n, write=not args.no_write)
    metrics = payload["metrics"]
    print(
        f"mode={metrics['mode']} cases={metrics['n_cases']} "
        f"unsupported_before={metrics['unsupported_sentence_rate_before']} "
        f"unsupported_after={metrics['unsupported_sentence_rate_after']}"
    )


if __name__ == "__main__":
    main()
