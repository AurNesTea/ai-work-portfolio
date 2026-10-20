"""Per-task token log: time, model, and tokens for every CLI step."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "panel" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import snapshot_server  # noqa: E402
import usage_log  # noqa: E402


def _run(root: Path, run_id: str, started_at: str | None, events: list[dict]) -> None:
    run = root / "runs" / run_id
    run.mkdir(parents=True)
    status = {
        "run_id": run_id,
        "workflow_id": "smoke",
        "state": "succeeded",
        "step_id": None,
        "pid": None,
        "updated_at": "2026-10-01T00:00:00Z",
        "last_error": None,
        "dirty": False,
    }
    if started_at is not None:
        status["started_at"] = started_at
    (run / "status.json").write_text(json.dumps(status), encoding="utf-8")
    for ev in events:
        ev["run_id"] = run_id
    lines = [json.dumps(ev) for ev in events]
    (run / "usage_events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ev(agent: str, step_id: str, model: str, **tokens: int) -> dict:
    row = {
        "run_id": "x",
        "step_id": step_id,
        "agent": agent,
        "model_requested": "requested",
        "model_actual": model,
        "input_uncached": tokens.get("input_uncached", 0),
        "cache_read": tokens.get("cache_read", 0),
        "cache_write": tokens.get("cache_write", 0),
        "output": tokens.get("output", 0),
    }
    if "recorded_at" in tokens:
        row["recorded_at"] = tokens["recorded_at"]
    return row


def test_log_is_one_row_per_task(tmp_path: Path):
    _run(
        tmp_path,
        "aaa11111",
        "2026-09-20T16:00:00Z",
        [
            _ev("cursor", "step1", "Composer 2.5", input_uncached=100, cache_read=1, output=10),
            _ev(
                "claude",
                "step2",
                "claude-sonnet",
                input_uncached=5,
                output=6,
                recorded_at="2026-10-01T10:30:00Z",
            ),
        ],
    )
    _run(
        tmp_path,
        "bbb22222",
        "2026-09-20T15:59:59Z",
        [_ev("gemini", "step1", "gemini-2.5", input_uncached=40, cache_read=4, output=5)],
    )

    rows = usage_log.collect_usage_log(tmp_path)
    usds = [row.pop("usd") for row in rows]
    assert usds[0] is None
    assert usds[1] == pytest.approx((100 * 0.5 + 0.2 + 10 * 2.5) / 1_000_000)
    assert usds[2] is None
    assert rows == [
        {
            "at": "2026-10-01 18:30:00",
            "run_id": "aaa11111",
            "step_id": "step2",
            "agent": "claude",
            "role": "",
            "model": "claude-sonnet",
            "input_uncached": 5,
            "cache_read": 0,
            "cache_write": 0,
            "output": 6,
        },
        {
            "at": "2026-09-21 00:00:00",
            "run_id": "aaa11111",
            "step_id": "step1",
            "agent": "cursor",
            "role": "",
            "model": "Composer 2.5",
            "input_uncached": 100,
            "cache_read": 1,
            "cache_write": 0,
            "output": 10,
        },
        {
            "at": "2026-09-20 23:59:59",
            "run_id": "bbb22222",
            "step_id": "step1",
            "agent": "gemini",
            "role": "",
            "model": "gemini-2.5",
            "input_uncached": 40,
            "cache_read": 4,
            "cache_write": 0,
            "output": 5,
        },
    ]



def test_snapshot_log_ignores_history_limit(tmp_path: Path):
    for i in range(21):
        _run(
            tmp_path,
            f"r{i:02d}",
            "2026-09-21T04:00:00+08:00",
            [_ev("codex", "step1", "gpt-5", output=1)],
        )
    snap = snapshot_server.build_snapshot(tmp_path, None)
    assert len(snap["history"]) == 20
    assert len(snap["usage_log"]) == 21
    assert snap["usage_log"][0]["model"] == "gpt-5"
    assert "usage_by_model" in snap


def test_naive_recorded_at_still_gets_taipei_at(tmp_path: Path):
    _run(
        tmp_path,
        "naive001",
        "2026-09-20T16:00:00Z",
        [
            _ev(
                "cursor",
                "step1",
                "Composer 2.5",
                input_uncached=1,
                recorded_at="2026-10-01T10:30:00",
            )
        ],
    )
    rows = usage_log.collect_usage_log(tmp_path)
    assert rows[0]["at"] == "2026-10-01 18:30:00"
    assert usage_log.summarize_month(rows, "2026-10")["input_uncached"] == 1


def test_invalid_recorded_at_falls_back_to_started_at(tmp_path: Path):
    _run(
        tmp_path,
        "badtime1",
        "2026-09-30T16:00:00Z",
        [
            _ev(
                "cursor",
                "step1",
                "Composer 2.5",
                input_uncached=2,
                recorded_at="not-a-timestamp",
            )
        ],
    )
    rows = usage_log.collect_usage_log(tmp_path)
    assert rows[0]["at"] == "2026-10-01 00:00:00"
    assert usage_log.summarize_month(rows, "2026-10")["input_uncached"] == 2


def test_ledger_only_manual_row_appears(tmp_path: Path):
    from aiwork.models import UsageEvent
    from aiwork.usage_db import insert_event

    insert_event(
        tmp_path,
        UsageEvent(
            run_id="manual01",
            step_id="agy",
            agent="gemini",
            model_requested="gemini-3.8-flash-high",
            model_actual="Gemini 3.8 Flash (High)",
            input_uncached=9,
            cache_read=0,
            cache_write=0,
            output=3,
            recorded_at="2026-10-11T02:00:00Z",
            effort="high",
        ),
        "manual",
        source="manual",
    )
    rows = usage_log.collect_usage_log(tmp_path)
    assert any(row["run_id"] == "manual01" and row["output"] == 3 for row in rows)
    assert any(row["at"].startswith("2026-10-11") for row in rows)
