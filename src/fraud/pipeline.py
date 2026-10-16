"""Entry point: ``python -m fraud.pipeline`` runs the existing scanner.

This is a thin wrapper so the legacy ``python audit_scanner.py`` script keeps
working unchanged while new code uses the ``fraud`` package layout.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import audit_scanner  # noqa: E402  (path set up above)


def main() -> None:
    """Run all domain scans and export the report via the legacy scanner."""
    audit_scanner.main()


if __name__ == "__main__":
    main()
