"""Evaluation harness (module P3).

Joins the rule engine's flags against the simulator's ground-truth labels
(``data/labels.csv``) and reports precision / recall / F1 per rule at three
prevalence levels. This is the *only* module that reads labels; the detection
code (``fraud.rules``, ``fraud.pipeline``) never does.

Everything here is **in-sample**: each rule is scored against the very
injections the simulator planted for it, so the numbers are optimistic and are
*not* a generalization estimate.

Run with::

    make eval
    # or, with ``src`` on PYTHONPATH:
    python -m fraud.evaluate
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

logging.disable(logging.CRITICAL)

import pandas as pd  # noqa: E402
from sklearn.metrics import precision_recall_fscore_support  # noqa: E402

from fraud.config import get_config  # noqa: E402
from fraud.rules import get_rules  # noqa: E402

#: Prevalence levels reported by the sensitivity run.
LEVELS: tuple[float, ...] = (0.02, 0.05, 0.10)
METRICS_JSON = REPO_ROOT / "reports" / "metrics.json"
METRICS_MD = REPO_ROOT / "reports" / "metrics.md"

CAVEAT = (
    "In-sample: every rule is scored against the same injections the simulator "
    "planted. The rules were written to catch those patterns, so precision and "
    "recall are optimistic and are NOT a generalization estimate."
)

# Fraud type each rule injects (display metadata only, no numbers).
RULE_FRAUD_TYPE: dict[str, str] = {
    "RULE_001": "invalid_mobile",
    "RULE_002": "underage_jobcard",
    "RULE_003": "suspicious_age",
    "RULE_004": "mega_family",
    "RULE_005": "impossible_human",
    "RULE_006": "ghost_project",
    "RULE_007": "wage_theft",
    "RULE_008": "free_money",
    "RULE_009": "time_travel",
    "RULE_010": "bio_mismatch",
    "RULE_011": "massive_upcoding",
    "RULE_012": "blacklisted_hospital",
    "RULE_013": "mobile_sharing",
    "RULE_017": "muster_cartel",
    "RULE_021": "procedure_mill",
    "RULE_025": "cross_scheme",
}

# Flat structural types: fixed or floored injected volume, so they do not
# measure prevalence sensitivity. ``mega_family`` is flat only where its floor
# binds (see :func:`section_for`).
FLAT_RULES = {"RULE_004", "RULE_021", "RULE_025"}

DETECTORS: list[dict[str, Any]] = [
    {
        "detector": "RULES_ONLY",
        "evaluation_status": "in-sample",
        "precision": None,
        "recall": None,
        "f1": None,
        "note": "per-rule rows carry the metrics; no single aggregate is computed",
    },
    {
        "detector": "ML_ONLY",
        "evaluation_status": "not built (P4)",
        "precision": None,
        "recall": None,
        "f1": None,
        "note": None,
    },
    {
        "detector": "HYBRID",
        "evaluation_status": "not built (P4)",
        "precision": None,
        "recall": None,
        "f1": None,
        "note": None,
    },
]


# =============================================================================
# LABELS
# =============================================================================

def load_labels(path: str | Path) -> pd.DataFrame:
    """Load ground-truth labels, failing loudly if they are missing."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Ground-truth labels not found: {path}\n"
            "Regenerate the synthetic data first:\n"
            "    python data_simulator.py\n"
            "or run the whole harness with: make eval"
        )
    return pd.read_csv(path, keep_default_na=False)


def injected_by_rule(labels: pd.DataFrame) -> dict[str, set[str]]:
    """``{rule_id: {record_id, ...}}`` from ``injected_rule_id`` (recall truth)."""
    mapping: dict[str, set[str]] = {}
    for record_id, rule_ids in zip(
        labels["record_id"], labels["injected_rule_id"], strict=True
    ):
        for rule_id in str(rule_ids).split("|"):
            rule_id = rule_id.strip()
            if rule_id:
                mapping.setdefault(rule_id, set()).add(str(record_id))
    return mapping


def nonfraud_ids(labels: pd.DataFrame) -> set[str]:
    """Record ids labelled ``is_fraud == 0`` (a flag on any of these is an FP)."""
    mask = labels["is_fraud"].astype(int) == 0
    return set(labels.loc[mask, "record_id"].astype(str))


def fraud_ids(labels: pd.DataFrame) -> set[str]:
    """Record ids labelled ``is_fraud == 1`` (injected fraud of some type)."""
    mask = labels["is_fraud"].astype(int) == 1
    return set(labels.loc[mask, "record_id"].astype(str))


# =============================================================================
# SCORING
# =============================================================================

def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Precision/recall/F1 via sklearn from the rule-level confusion counts.

    A flag on an ``is_fraud=0`` record is an FP; the recall denominator is the
    records injected with this rule. ``OTHER_FRAUD`` (cross-rule overlap) is
    excluded from both. TN is irrelevant to these three metrics, so the arrays
    only carry TP/FP/FN.
    """
    y_true = [1] * tp + [0] * fp + [1] * fn
    y_pred = [1] * tp + [1] * fp + [0] * fn
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    return float(precision), float(recall), float(f1)


def section_for(rule_id: str, injected_count: int, cfg: Any) -> str:
    """Return ``"flat"`` or ``"scaling"`` for a rule at one prevalence level."""
    if rule_id in ("RULE_021", "RULE_025"):
        return "flat"
    if rule_id == "RULE_004":  # mega_family: flat only while its floor binds
        floor = cfg.civil_registry.max_family_size + 1
        return "flat" if injected_count <= floor else "scaling"
    return "scaling"


@dataclass
class RuleScore:
    """One rule's in-sample score at one prevalence level."""

    rule_id: str
    fraud_type: str
    section: str
    evaluation_status: str
    flagged: int
    injected: int
    tp: int
    fp: int
    other_fraud: int
    fn: int
    precision: float | None
    recall: float | None
    f1: float | None


def rule_scores(
    labels: pd.DataFrame,
    flags_by_rule: dict[str, set[str]],
    min_events: int,
    cfg: Any | None = None,
) -> list[RuleScore]:
    """Score every registered rule against ``labels`` for one prevalence.

    Every flag lands in exactly one of three buckets:

    * ``tp`` - ``is_fraud=1`` and injected with *this* rule;
    * ``other_fraud`` - ``is_fraud=1`` but injected with a *different* rule
      (cross-rule overlap: not a true positive, and not a false positive in the
      ``is_fraud`` sense);
    * ``fp`` - ``is_fraud=0``.

    Precision is ``TP / (TP + FP)`` (``other_fraud`` is not in the denominator);
    recall is ``TP / (TP + FN)`` with the recall denominator the records injected
    with this rule.
    """
    cfg = cfg or get_config()
    injected = injected_by_rule(labels)
    nonfraud = nonfraud_ids(labels)
    fraud = fraud_ids(labels)

    scores: list[RuleScore] = []
    for rule in get_rules():
        rule_id = rule.id
        flagged = set(flags_by_rule.get(rule_id, set()))
        positives = injected.get(rule_id, set())
        tp_ids = flagged & positives
        other_ids = flagged & (fraud - positives)
        fp_ids = flagged & nonfraud

        uncovered = flagged - (tp_ids | other_ids | fp_ids)
        if uncovered:
            raise EvaluationError(
                f"{rule_id}: {len(uncovered)} flag(s) fall outside TP / "
                f"OTHER_FRAUD / FP: {sorted(uncovered)[:5]}"
            )

        tp, fp, other_fraud = len(tp_ids), len(fp_ids), len(other_ids)
        fn = len(positives - flagged)

        if len(positives) < min_events:
            precision = recall = f1 = None
            status = "not evaluable"
        else:
            precision, recall, f1 = _prf(tp, fp, fn)
            status = "in-sample"

        scores.append(RuleScore(
            rule_id=rule_id,
            fraud_type=RULE_FRAUD_TYPE.get(rule_id, rule.name),
            section=section_for(rule_id, len(positives), cfg),
            evaluation_status=status,
            flagged=len(flagged),
            injected=len(positives),
            tp=tp,
            fp=fp,
            other_fraud=other_fraud,
            fn=fn,
            precision=precision,
            recall=recall,
            f1=f1,
        ))
    return scores


# =============================================================================
# RECONCILIATION GUARD
# =============================================================================

class EvaluationError(RuntimeError):
    """Raised when the evaluation output is internally inconsistent."""


def _field(row: Any, key: str) -> Any:
    """Read ``key`` from a mapping or an object (RuleScore)."""
    return row[key] if isinstance(row, dict) else getattr(row, key)


def reconciliation_violations(rows: Sequence[Any]) -> list[str]:
    """Return one message per row where ``flagged != TP + FP + OTHER_FRAUD``.

    Every emitted flag must be in exactly one bucket: a true positive (record
    injected with this rule), an ``OTHER_FRAUD`` overlap (a fraud record injected
    with a *different* rule), or a false positive (``is_fraud=0``). If they do
    not add up, some flag is unaccounted and the row is not trustworthy.
    """
    violations: list[str] = []
    for row in rows:
        flagged = _field(row, "flagged")
        tp = _field(row, "tp")
        fp = _field(row, "fp")
        other = _field(row, "other_fraud")
        total = tp + fp + other
        if flagged != total:
            violations.append(
                f"{_field(row, 'rule_id')}: flagged={flagged} != "
                f"TP+FP+OTHER_FRAUD={total} "
                f"(unaccounted flags={flagged - total})"
            )
    return violations


def assert_reconciliation(rows: Sequence[Any]) -> None:
    """Fail loudly if any row breaks ``flagged == TP + FP + OTHER_FRAUD``."""
    violations = reconciliation_violations(rows)
    if violations:
        raise EvaluationError(
            "flagged != TP + FP + OTHER_FRAUD: every emitted flag must be a "
            "true positive (record injected with this rule), an OTHER_FRAUD "
            "overlap (fraud record injected with another rule), or a false "
            "positive (is_fraud=0).\n  " + "\n  ".join(violations)
        )


def payload_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every per-rule row in the payload, across all levels and sections."""
    rows: list[dict[str, Any]] = []
    for sections in payload["levels"].values():
        rows.extend(sections["scaling_types"])
        rows.extend(sections["flat_types"])
    return rows


# =============================================================================
# DATA GENERATION + SCAN (one directory per prevalence)
# =============================================================================

def generate_level(prevalence: float, workdir: Path) -> None:
    """Regenerate the synthetic data for ``prevalence`` into ``workdir``."""
    workdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONUTF8="1")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "data_simulator.py"),
         "--prevalence", str(prevalence)],
        cwd=workdir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"data_simulator.py failed at prevalence {prevalence}:\n"
            + result.stderr.decode("utf-8", "replace")
        )


def scan_flags(workdir: Path) -> dict[str, set[str]]:
    """Run the rule engine on ``workdir/data`` and return ``{rule: {record}}``."""
    import audit_scanner

    previous = Path.cwd()
    os.chdir(workdir)
    try:
        scanner = audit_scanner.MasterFraudScanner()
        with contextlib.redirect_stdout(io.StringIO()):
            scanner.run_all_scans()
        flags: dict[str, set[str]] = {}
        for report in scanner.all_reports:
            for flag in report.flags:
                flags.setdefault(flag["rule_id"], set()).add(report.record_id)
        return flags
    finally:
        os.chdir(previous)


def evaluate_level(prevalence: float, root: Path, cfg: Any) -> list[RuleScore]:
    """Generate + scan one prevalence and score every rule."""
    workdir = root / f"p{int(round(prevalence * 100)):02d}"
    generate_level(prevalence, workdir)
    flags = scan_flags(workdir)
    labels = load_labels(workdir / "data" / "labels.csv")
    return rule_scores(labels, flags, cfg.simulator.min_events_per_type, cfg)


# =============================================================================
# REPORT
# =============================================================================

def build_payload(
    levels: dict[str, list[RuleScore]], cfg: Any
) -> dict[str, Any]:
    """Assemble the JSON payload (every row carries ``evaluation_status``)."""
    payload: dict[str, Any] = {
        "generated_by": "fraud.evaluate",
        "caveat": CAVEAT,
        "min_events_per_type": cfg.simulator.min_events_per_type,
        "mega_family_floor": cfg.civil_registry.max_family_size + 1,
        "detectors": DETECTORS,
        "levels": {},
    }
    for level, scores in levels.items():
        payload["levels"][level] = {
            "scaling_types": [asdict(s) for s in scores if s.section == "scaling"],
            "flat_types": [asdict(s) for s in scores if s.section == "flat"],
        }
    rows = payload_rows(payload)
    violations = reconciliation_violations(rows)
    payload["reconciliation_ok"] = not violations
    payload["reconciliation_violations"] = violations
    return payload


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _table(scores: Sequence[dict[str, Any]]) -> list[str]:
    lines = [
        "| rule | fraud_type | status | flagged | injected | TP | FP "
        "| OTHER_FRAUD | FN | precision | recall | F1 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        lines.append(
            f"| {s['rule_id']} | {s['fraud_type']} | {s['evaluation_status']} "
            f"| {s['flagged']} | {s['injected']} | {s['tp']} | {s['fp']} "
            f"| {s['other_fraud']} | {s['fn']} | {_fmt(s['precision'])} "
            f"| {_fmt(s['recall'])} | {_fmt(s['f1'])} |"
        )
    return lines


def _other_fraud_lines(payload: dict[str, Any]) -> list[str]:
    """Per-rule cross-rule overlap (``OTHER_FRAUD``) at every prevalence."""
    lines = [
        "## Cross-rule overlap (OTHER_FRAUD)",
        "",
        "Cross-rule overlap is measured, not a false positive. High overlap means "
        "the rules co-fire on the same records and the per-rule numbers are not "
        "independent.",
        "",
        "| rule | " + " | ".join(payload["levels"]) + " |",
        "|---" * (1 + len(payload["levels"])) + "|",
    ]
    rules: list[str] = []
    for sections in payload["levels"].values():
        for row in sections["scaling_types"] + sections["flat_types"]:
            if row["rule_id"] not in rules:
                rules.append(row["rule_id"])
    for rule_id in rules:
        counts = []
        for sections in payload["levels"].values():
            row = next(
                (r for r in sections["scaling_types"] + sections["flat_types"]
                 if r["rule_id"] == rule_id),
                None,
            )
            counts.append(str(row["other_fraud"]) if row else "n/a")
        lines.append(f"| {rule_id} | " + " | ".join(counts) + " |")
    lines.append("")
    return lines


def _flat_classification_lines(payload: dict[str, Any]) -> list[str]:
    """Explain the flat/scaling split using the *observed* injected counts."""
    floor = payload["mega_family_floor"]
    lines = [
        "## Flat-type classification",
        "",
        "- `procedure_mill` (RULE_021) and `cross_scheme` (RULE_025): injected "
        "volume is fixed/structural (one mill group, a fixed beneficiary count), "
        "so they are flat at every level and do not measure prevalence "
        "sensitivity.",
        f"- `mega_family` (RULE_004): classified flat only while its injected "
        f"count equals the structural floor (`max_family_size + 1` = {floor}); "
        "above the floor it scales with prevalence and is classified scaling.",
    ]
    observed: list[str] = []
    for level, sections in payload["levels"].items():
        row = next(
            (r for r in sections["scaling_types"] + sections["flat_types"]
             if r["rule_id"] == "RULE_004"),
            None,
        )
        if row is not None:
            observed.append(
                f"{level} -> {row['injected']} injected ({row['section']})"
            )
    if observed:
        lines.append(f"  Observed for `mega_family`: {'; '.join(observed)}.")
    lines.append("")
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    """Render ``payload`` as ``reports/metrics.md`` (caveat above every table)."""
    lines = [
        "# Evaluation metrics (in-sample)",
        "",
        f"> **In-sample caveat.** {payload['caveat']}",
        "",
        "Rule-level precision, recall and F1 only: each rule emits a binary flag, "
        "so PR-AUC does not apply. `not evaluable` = fewer than "
        f"{payload['min_events_per_type']} injected events at that prevalence.",
        "",
    ]
    for level, sections in payload["levels"].items():
        lines.append(f"## Prevalence {level} (in-sample)")
        lines.append("")
        lines.append(
            "> Scored against the simulator's own injections at this prevalence; "
            "not a generalization estimate."
        )
        lines.append("")
        lines.append("### Scaling types (counts scale with prevalence)")
        lines.append("")
        lines.extend(_table(sections["scaling_types"]))
        lines.append("")
        lines.append("### Flat types (do not measure prevalence sensitivity)")
        lines.append("")
        lines.append(
            "Fixed/floored injected volume: `procedure_mill`, `cross_scheme`, and "
            "`mega_family` where its floor binds."
        )
        lines.append("")
        lines.extend(_table(sections["flat_types"]))
        lines.append("")
    lines.extend(_flat_classification_lines(payload))
    lines.extend(_other_fraud_lines(payload))
    if not payload["reconciliation_ok"]:
        lines.append("## Reconciliation check")
        lines.append("")
        lines.append(
            "> **FAILED:** `flagged != TP + FP + OTHER_FRAUD` for the rows below. "
            "Every emitted flag must be a TP (record injected with this rule), an "
            "OTHER_FRAUD overlap (fraud record injected with another rule), or an "
            "FP (`is_fraud=0`); an unaccounted flag means the row is not "
            "trustworthy."
        )
        lines.append("")
        for violation in payload["reconciliation_violations"]:
            lines.append(f"- {violation}")
        lines.append("")
    lines.append("## Detectors")
    lines.append("")
    lines.append("| detector | status | precision | recall | F1 |")
    lines.append("|---|---|---|---|---|")
    for detector in payload["detectors"]:
        lines.append(
            f"| {detector['detector']} | {detector['evaluation_status']} "
            f"| {_fmt(detector['precision'])} | {_fmt(detector['recall'])} "
            f"| {_fmt(detector['f1'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def run(
    levels: Sequence[float] = LEVELS,
    root: str | Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Regenerate, scan and score every level; write metrics.json + metrics.md."""
    cfg = get_config()
    base = Path(root) if root is not None else REPO_ROOT / "data"
    results = {
        f"{prevalence:.2f}": evaluate_level(prevalence, base, cfg)
        for prevalence in levels
    }
    payload = build_payload(results, cfg)
    if write:
        METRICS_JSON.parent.mkdir(parents=True, exist_ok=True)
        METRICS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        METRICS_MD.write_text(render_markdown(payload), encoding="utf-8")
    return payload


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="In-sample evaluation harness.")
    parser.add_argument("--levels", nargs="+", type=float, default=list(LEVELS))
    parser.add_argument("--root", default=None,
                        help="Base dir for the per-level data (default: data/).")
    parser.add_argument("--no-write", action="store_true",
                        help="Print the report without writing metrics files.")
    args = parser.parse_args(argv)
    payload = run(levels=args.levels, root=args.root, write=not args.no_write)
    print(render_markdown(payload))
    # Fail *after* the report and metrics files are produced, so the broken rows
    # are still inspectable (make eval exits non-zero until they reconcile).
    assert_reconciliation(payload_rows(payload))


if __name__ == "__main__":
    main()
