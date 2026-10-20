import json
from pathlib import Path

from aiwork.adapters.base import AdapterResult
from aiwork.ledger import append_usage, read_usage
from aiwork.models import StepSpec, UsageEvent
from aiwork.runner import _write_event


def test_append_and_read_usage(tmp_path: Path):
    run_dir = tmp_path / "r1"
    run_dir.mkdir()
    ev = UsageEvent(
        run_id="r1",
        step_id="s1",
        agent="cursor",
        model_requested="m",
        model_actual="m",
        input_uncached=1,
        cache_read=2,
        cache_write=3,
        output=4,
    )
    append_usage(run_dir, ev)
    rows = read_usage(run_dir)
    assert len(rows) == 1
    assert rows[0].total_input() == 6
    assert rows[0].recorded_at is None


def test_write_event_stamps_recorded_at(tmp_path: Path):
    step = StepSpec(id="step1", agent="cursor", model="composer-2", prompt_file="p.md")
    result = AdapterResult(
        exit_code=0,
        session_id=None,
        model_actual="Composer 2.5",
        input_uncached=1,
        cache_read=2,
        cache_write=3,
        output=4,
        cost_usd=None,
        dirty=False,
        stdout="",
        stderr="",
    )
    _write_event(tmp_path, run_id="r1", step=step, result=result)
    row = json.loads((tmp_path / "usage_events.jsonl").read_text(encoding="utf-8"))
    assert row["model_actual"] == "Composer 2.5"
    assert row["recorded_at"]
