"""Taipei calendar month and public list-price dollars."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "panel" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import usage_log  # noqa: E402
from aiwork.pricing import quote_usd  # noqa: E402


def test_priced_model_charges_each_token_kind():
    # Composer 2.5 has no cache-write price, so those tokens add 0.
    usd = quote_usd("Composer 2.5", 100, 1, 7, 10)
    assert usd == pytest.approx((100 * 0.5 + 1 * 0.2 + 10 * 2.5) / 1_000_000)


def test_dated_model_id_uses_the_list_price():
    usd = quote_usd(
        "claude-sonnet-4-5-20250929",
        1_000_000,
        1_000_000,
        1_000_000,
        1_000_000,
    )
    assert usd == pytest.approx(3 + 0.30 + 3.75 + 15)


def test_model_without_a_public_price_is_empty():
    assert quote_usd("claude-sonnet", 5, 0, 0, 6) is None
    assert quote_usd("gemini-2.5", 40, 4, 0, 5) is None


def test_usage_row_ignores_cli_cost(tmp_path: Path):
    run = tmp_path / "runs" / "priced01"
    run.mkdir(parents=True)
    status = {
        "run_id": "priced01",
        "workflow_id": "smoke",
        "state": "succeeded",
        "step_id": None,
        "pid": None,
        "started_at": "2026-09-30T16:00:00Z",
        "updated_at": "2026-10-01T00:00:00Z",
        "last_error": None,
        "dirty": False,
    }
    (run / "status.json").write_text(json.dumps(status), encoding="utf-8")
    event = {
        "run_id": "priced01",
        "step_id": "step1",
        "agent": "cursor",
        "model_actual": "Composer 2.5",
        "input_uncached": 1_000_000,
        "cache_read": 0,
        "cache_write": 0,
        "output": 0,
        "cost_usd": 99,
    }
    (run / "usage_events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

    rows = usage_log.collect_usage_log(tmp_path)
    assert rows[0]["usd"] == pytest.approx(0.5)
    assert rows[0]["usd"] != 99


def test_month_total_uses_taipei_calendar_bounds(tmp_path: Path):
    _write(
        tmp_path,
        "oct00001",
        "2026-09-30T16:00:00Z",
        "gpt-5.5",
        output=1_000_000,
    )
    _write(
        tmp_path,
        "sep00001",
        "2026-09-30T15:59:59Z",
        "not-a-listed-model",
        output=3,
    )

    october = usage_log.summarize_month(
        usage_log.collect_usage_log(tmp_path), "2026-10"
    )
    september = usage_log.summarize_month(
        usage_log.collect_usage_log(tmp_path), "2026-09"
    )
    assert october["output"] == 1_000_000
    assert october["usd"] == pytest.approx(30)
    assert september["output"] == 3
    assert september["usd"] is None


def _write(
    root: Path,
    run_id: str,
    started_at: str,
    model: str,
    output: int,
) -> None:
    run = root / "runs" / run_id
    run.mkdir(parents=True)
    status = {
        "run_id": run_id,
        "workflow_id": "smoke",
        "state": "succeeded",
        "step_id": None,
        "pid": None,
        "started_at": started_at,
        "updated_at": started_at,
        "last_error": None,
        "dirty": False,
    }
    (run / "status.json").write_text(json.dumps(status), encoding="utf-8")
    event = {
        "run_id": run_id,
        "step_id": "step1",
        "agent": "codex",
        "model_actual": model,
        "input_uncached": 0,
        "cache_read": 0,
        "cache_write": 0,
        "output": output,
    }
    (run / "usage_events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
