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


def compute_metrics(
    results: list[CaseResult], mode: str, model: str | None = None
) -> dict[str, Any]:
    """Aggregate per-case results, keeping before/after rates separate.

    Sentence counts use the same splitter for both passes. The final-draft
    unsupported rate is reported against the final-draft denominator and
    against the fixed first-draft denominator, so a draft that shrinks cannot
    look better only because it has fewer sentences.
    """
    first_total = sum(result.verification_first.total for result in results)
    first_bad = sum(result.verification_first.unsupported for result in results)
    final_total = sum(result.verification.total for result in results)
    final_bad = sum(result.verification.unsupported for result in results)
    statuses = Counter(result.status for result in results)
    requested = sum(len(result.tool_call_log) for result in results)
    executed = sum(
        1 for result in results for entry in result.tool_call_log if entry["executed"]
    )
    capped = sum(
        1 for result in results for entry in result.tool_call_log if entry["capped"]
    )
    malformed = sum(
        1 for result in results for entry in result.tool_call_log if entry["malformed"]
    )
    revisions_accepted = sum(result.revisions_accepted for result in results)
    revisions_rejected = sum(result.revisions for result in results) - revisions_accepted
    return {
        "generated_by": "fraud.agent.run",
        "disclaimer": DISCLAIMER,
        "mode": mode,
        "model": model,
        "n_cases": len(results),
        "unsupported_sentence_rate_before": _rate(first_bad, first_total),
        "unsupported_sentence_rate_after": _rate(final_bad, final_total),
        "sentences_before": first_total,
        "unsupported_before": first_bad,
        "sentences_after": final_total,
        "unsupported_after": final_bad,
        "sentences_first": first_total,
        "unsupported_first": first_bad,
        "rate_first": _rate(first_bad, first_total),
        "sentences_final": final_total,
        "unsupported_final": final_bad,
        "rate_final_final_denominator": _rate(final_bad, final_total),
        "rate_final_first_denominator": _rate(final_bad, first_total),
        "tool_calls_per_case": _summary([result.tool_calls for result in results]),
        "tool_requests_per_case": _summary(
            [len(result.tool_call_log) for result in results]
        ),
        "tool_call_totals": {
            "requested": requested,
            "executed": executed,
            "capped": capped,
            "malformed": malformed,
        },
        "tool_calls_capped_total": capped,
        "tool_calls_malformed_total": malformed,
        "revisions_per_case": _summary([result.revisions for result in results]),
        "revisions_accepted_total": revisions_accepted,
        "revisions_rejected_total": revisions_rejected,
        "cases_revision_rejected": sum(
            1 for result in results if result.revision_rejected
        ),
        "status_counts": dict(sorted(statuses.items())),
    }


def run(
    n: int = 20,
    write: bool = True,
    client: LLMClient | None = None,
    tables: dict[str, Any] | None = None,
    rules: list[Any] | None = None,
    cfg: Any | None = None,
    cases_path: str | Path | None = None,
    metrics_path: str | Path | None = None,
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
    metrics = compute_metrics(results, client.mode, client.config.model)

    if write:
        cases_file = Path(cases_path) if cases_path is not None else CASES_JSON
        metrics_file = Path(metrics_path) if metrics_path is not None else METRICS_JSON
        cases_file.parent.mkdir(parents=True, exist_ok=True)
        metrics_file.parent.mkdir(parents=True, exist_ok=True)
        cases_file.write_text(
            json.dumps([result.to_dict() for result in results], indent=2),
            encoding="utf-8",
        )
        metrics_file.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        logger.info("Wrote %s and %s", cases_file, metrics_file)

    return {"cases": [result.to_dict() for result in results], "metrics": metrics}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the agent layer over the top flagged records."
    )
    parser.add_argument("--n", type=int, default=20, help="number of cases")
    parser.add_argument("--no-write", action="store_true", help="do not write reports")
    parser.add_argument(
        "--cases-path", default=str(CASES_JSON), help="where to write the cases JSON"
    )
    parser.add_argument(
        "--metrics-path",
        default=str(METRICS_JSON),
        help="where to write the metrics JSON",
    )
    args = parser.parse_args(argv)

    payload = run(
        n=args.n,
        write=not args.no_write,
        cases_path=args.cases_path,
        metrics_path=args.metrics_path,
    )
    metrics = payload["metrics"]
    print(
        f"mode={metrics['mode']} cases={metrics['n_cases']} "
        f"unsupported_before={metrics['unsupported_sentence_rate_before']} "
        f"unsupported_after={metrics['unsupported_sentence_rate_after']}"
    )


if __name__ == "__main__":
    main()
