"""Guard: every 3-decimal figure in the README lives in the generated block.

Metrics must come from the generated reports, never be typed by hand. The
hybrid report's rendered section is the one place the README may carry a
3-decimal figure, and it is fenced by BEGIN/END markers. Anything else (in
particular the Limitations section) must stay free of them.
"""
from __future__ import annotations

import re
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"
BEGIN = "<!-- BEGIN GENERATED: hybrid -->"
END = "<!-- END GENERATED: hybrid -->"
THREE_DECIMAL = re.compile(r"\d\.\d{3}")


def _lines() -> list[str]:
    return README.read_text(encoding="utf-8").splitlines()


def test_three_decimal_metrics_only_in_generated_block() -> None:
    lines = _lines()
    begin = next(i for i, line in enumerate(lines) if BEGIN in line)
    end = next(i for i, line in enumerate(lines) if END in line)
    assert begin < end, "BEGIN marker must come before END marker"

    offenders = [
        (i + 1, line)
        for i, line in enumerate(lines)
        if THREE_DECIMAL.search(line) and not begin < i < end
    ]
    assert not offenders, "3-decimal figure(s) outside the generated block:\n" + "\n".join(
        f"  line {n}: {text}" for n, text in offenders
    )


def test_limitations_has_no_three_decimal_metrics() -> None:
    lines = _lines()
    start = next(
        i for i, line in enumerate(lines) if line.strip() == "## Limitations"
    )
    offenders = [
        (start + j + 1, line)
        for j, line in enumerate(lines[start:])
        if THREE_DECIMAL.search(line)
    ]
    assert not offenders, "3-decimal figure(s) in Limitations:\n" + "\n".join(
        f"  line {n}: {text}" for n, text in offenders
    )
