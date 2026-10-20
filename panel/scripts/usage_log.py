"""One row per CLI step: Taipei time, model used, tokens, and list price."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aiwork.usage_view import collect_usage_log, summarize_month  # noqa: E402

__all__ = ["collect_usage_log", "summarize_month"]
