"""Public per-token list prices. CLI-reported cost is not used."""
from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

_MILLION = Decimal(1_000_000)
_QUANTUM = Decimal("0.00000001")
_PRICES_PATH = Path(__file__).with_name("public_prices.json")
_CACHED_MTIME: float = 0.0
_RATES: dict = {}


def _get_rates() -> dict:
    global _CACHED_MTIME, _RATES
    try:
        mtime = _PRICES_PATH.stat().st_mtime
        if mtime != _CACHED_MTIME:
            _RATES = json.loads(_PRICES_PATH.read_text(encoding="utf-8"))["models"]
            _CACHED_MTIME = mtime
    except Exception:
        if not _RATES:
            _RATES = json.loads(_PRICES_PATH.read_text(encoding="utf-8"))["models"]
    return _RATES


_get_rates()


def quote_usd(
    model: str,
    input_uncached: int,
    cache_read: int,
    cache_write: int,
    output: int,
) -> float | None:
    """Return list-price USD, or None when that model has no public price.

    A listed model with no unit price for one token kind counts that kind as 0.
    Rates are the standard short-context price. Claude cache writes use the
    5-minute rate. Gemini cache reads use the context-caching token price.
    """
    rates = _get_rates().get(_model_key(model))
    if rates is None:
        return None
    counts = {
        "input": input_uncached,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "output": output,
    }
    total = Decimal(0)
    for name, count in counts.items():
        rate = rates.get(name)
        if rate is None:
            continue
        total += Decimal(str(rate)) * Decimal(int(count))
    quantized = (total / _MILLION).quantize(_QUANTUM, rounding=ROUND_HALF_UP)
    return float(quantized)


def _model_key(model: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", model.strip().lower())
    text = re.sub(r"-\d{8}$", "", text)
    return text.strip("-")
