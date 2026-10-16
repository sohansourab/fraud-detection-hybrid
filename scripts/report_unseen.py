#!/usr/bin/env python3
"""Report the rule flags on the unseen-typology records (module P2e).

Reads ``data/labels.csv`` and runs the scanner, then reports for each
``unseen_*`` fraud type how many of its records any existing rule flags. The
injections are designed not to match any rule, so the expected count is 0; a
non-zero count is a finding (a rule generalises to an unseen pattern) and is
reported as-is, never tuned away.

Usage::

    python scripts/report_unseen.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

logging.disable(logging.CRITICAL)

import pandas as pd  # noqa: E402

from fraud.config import get_config  # noqa: E402
from fraud.evaluate import scan_flags  # noqa: E402

LABELS = REPO_ROOT / "data" / "labels.csv"
REPORT_MD = REPO_ROOT / "reports" / "unseen_rule_flags.md"
MIN_EVENTS = get_config().simulator.min_events_per_type


def unseen_events(labels: pd.DataFrame) -> dict[str, set[str]]:
    """Map each ``unseen_*`` fraud type to the ids injected with it."""
    events: dict[str, set[str]] = {}
    for record_id, types in zip(labels["record_id"], labels["fraud_type"]):
        for name in str(types).split("|"):
            if name.startswith("unseen_"):
                events.setdefault(name, set()).add(str(record_id))
    return events


def build_report() -> dict:
    """Compute per-unseen-type event and rule-flag counts."""
    labels = pd.read_csv(LABELS, keep_default_na=False)
    events = unseen_events(labels)
    rule_flags = scan_flags(REPO_ROOT)

    rows = []
    for name in sorted(events):
        ids = events[name]
        fired = {
            rule_id: len(ids & flagged)
            for rule_id, flagged in rule_flags.items()
            if ids & flagged
        }
        rows.append({
            "fraud_type": name,
            "events": len(ids),
            "flagged": sum(fired.values()),
            "by_rule": dict(sorted(fired.items())),
            "evaluation_status": (
                "in-sample" if len(ids) >= MIN_EVENTS else "not evaluable"
            ),
        })
    return {
        "generated_by": "scripts/report_unseen.py",
        "caveat": (
            "Scores are on synthetic labels. The unseen injections are designed "
            "not to match any rule; a non-zero count is a finding, not a target."
        ),
        "min_events_per_type": MIN_EVENTS,
        "types": rows,
    }


def render_markdown(payload: dict) -> str:
    """Render ``reports/unseen_rule_flags.md``."""
    lines = [
        "# Rule flags on the unseen typologies (P2e)",
        "",
        f"> {payload['caveat']}",
        "",
        "| fraud_type | events | rule flags | rules that fired | status |",
        "|---|---|---|---|---|",
    ]
    for row in payload["types"]:
        rules = ", ".join(f"{r}={n}" for r, n in row["by_rule"].items()) or "none"
        lines.append(
            f"| {row['fraud_type']} | {row['events']} | {row['flagged']} "
            f"| {rules} | {row['evaluation_status']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    payload = build_report()
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(render_markdown(payload), encoding="utf-8")
    print("in-sample rule flags on unseen records, not generalization")
    for row in payload["types"]:
        rules = ", ".join(f"{r}={n}" for r, n in row["by_rule"].items()) or "none"
        print(
            f"   {row['fraud_type']:34s} events={row['events']:3d} "
            f"rule_flags={row['flagged']:3d}  {rules}"
        )
    print(f"wrote {REPORT_MD}")


if __name__ == "__main__":
    main()
