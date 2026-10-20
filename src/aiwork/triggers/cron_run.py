"""Thin entry for scheduled runs: `python -m aiwork.triggers.cron_run workflows/smoke.yaml`."""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m aiwork.triggers.cron_run <workflow.yaml> [aiwork run flags...]", file=sys.stderr)
        return 2
    # Delegate to Typer CLI
    from aiwork.cli import app

    return app(["run", *argv], standalone_mode=False) or 0


if __name__ == "__main__":
    raise SystemExit(main())
