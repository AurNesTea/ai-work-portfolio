"""Priced usage rows for the panel: ledger first, list-price dollars."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from aiwork.pricing import quote_usd
from aiwork.usage_db import import_repo, list_events

TAIPEI = ZoneInfo("Asia/Taipei")


def collect_usage_log(repo_root: Path) -> list[dict]:
    """Import this repo's run logs, then read that repo from the ledger."""
    import_repo(repo_root)
    pending: list[tuple[datetime | None, int, dict]] = []
    for seq, ev in enumerate(list_events(repo_root)):
        instant = _instant(ev.get("recorded_at"))
        if instant is None:
            run_id = str(ev.get("run_id") or "")
            instant = _instant(_started_at(repo_root, run_id))
        pending.append((instant, seq, _row(str(ev.get("run_id") or ""), ev, instant)))
    pending.sort(key=lambda item: (item[0] is None, _neg(item[0]), -item[1]))
    return [row for _, _, row in pending]


def summarize_month(rows: list[dict], month: str) -> dict:
    """Sum one Taipei calendar month. Unlisted models leave usd empty."""
    chosen = [
        row
        for row in rows
        if str(row.get("at") or "").startswith(month + "-")
        or str(row.get("at") or "").startswith(month + " ")
    ]
    priced = [
        row["usd"]
        for row in chosen
        if isinstance(row.get("usd"), (int, float)) and not isinstance(row.get("usd"), bool)
    ]
    return {
        "month": month,
        "input_uncached": sum(int(row["input_uncached"]) for row in chosen),
        "cache_read": sum(int(row["cache_read"]) for row in chosen),
        "cache_write": sum(int(row["cache_write"]) for row in chosen),
        "output": sum(int(row["output"]) for row in chosen),
        "usd": None if not priced else float(sum(priced)),
    }


def collect_usage_log_json(repo_root: str | Path) -> str:
    """JSON array for desktop shells that shell out to Python."""
    return json.dumps(collect_usage_log(Path(repo_root)))


def _row(run_id: str, ev: dict, instant: datetime | None) -> dict:
    model = str(ev.get("model_actual") or "unknown")
    input_uncached = int(ev.get("input_uncached") or 0)
    cache_read = int(ev.get("cache_read") or 0)
    cache_write = int(ev.get("cache_write") or 0)
    output = int(ev.get("output") or 0)
    return {
        "at": "" if instant is None else instant.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S"),
        "run_id": str(ev.get("run_id") or run_id),
        "step_id": str(ev.get("step_id") or ""),
        "agent": str(ev.get("agent") or ""),
        "role": str(ev.get("dispatch_role") or ""),
        "model": model,
        "input_uncached": input_uncached,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "output": output,
        "usd": quote_usd(model, input_uncached, cache_read, cache_write, output),
    }


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _started_at(repo_root: Path, run_id: str) -> str:
    if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        return ""
    path = Path(repo_root) / "runs" / run_id / "status.json"
    if not path.is_file():
        return ""
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(status, dict):
        return ""
    value = status.get("started_at")
    return value if isinstance(value, str) else ""


def _neg(moment: datetime | None) -> float:
    if moment is None:
        return 0
    return -moment.timestamp()
