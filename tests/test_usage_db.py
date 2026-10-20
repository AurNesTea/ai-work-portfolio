"""Long-term usage ledger: one SQLite file for every project."""

import json
from pathlib import Path

from aiwork.adapters.base import AdapterResult
from aiwork.models import StepSpec, UsageEvent
from aiwork.runner import _write_event
from aiwork.usage_db import import_repo, insert_event, list_events, usage_db_path


def _event(step_id: str, recorded_at: str, output: int = 1) -> UsageEvent:
    return UsageEvent(
        run_id="run1",
        step_id=step_id,
        agent="cursor",
        model_requested="composer-2",
        model_actual="Composer 2.5",
        input_uncached=10,
        cache_read=2,
        cache_write=3,
        output=output,
        recorded_at=recorded_at,
        effort="high",
    )


def test_insert_is_idempotent(tmp_path: Path):
    repo = tmp_path / "proj"
    event = _event("step1", "2026-10-01T10:30:00Z")
    assert insert_event(repo, event, "smoke", source="run")
    assert not insert_event(repo, event, "smoke", source="run")
    rows = list_events(repo)
    assert len(rows) == 1
    assert rows[0]["workflow_id"] == "smoke"
    assert rows[0]["source"] == "run"
    assert rows[0]["effort"] == "high"
    assert rows[0]["output"] == 1
    assert "cost_usd" not in rows[0]


def test_two_repos_stay_separate(tmp_path: Path):
    first = tmp_path / "one"
    second = tmp_path / "two"
    insert_event(first, _event("step1", "2026-10-01T00:00:00Z", 4), "a")
    insert_event(second, _event("step1", "2026-10-02T00:00:00Z", 9), "b")
    assert [row["output"] for row in list_events(first)] == [4]
    assert [row["output"] for row in list_events()] == [4, 9]
    assert usage_db_path().is_file()


def test_import_reads_jsonl_and_survives_deletion(tmp_path: Path):
    repo = tmp_path / "proj"
    run = repo / "runs" / "abc"
    run.mkdir(parents=True)
    status = {
        "run_id": "abc",
        "workflow_id": "home",
        "state": "succeeded",
        "started_at": "2026-09-20T16:00:00Z",
        "updated_at": "2026-09-20T16:00:00Z",
    }
    (run / "status.json").write_text(json.dumps(status), encoding="utf-8")
    event = {
        "run_id": "abc",
        "step_id": "step1",
        "agent": "claude",
        "model_requested": "requested",
        "model_actual": "claude-sonnet",
        "input_uncached": 5,
        "output": 6,
    }
    (run / "usage_events.jsonl").write_text(
        json.dumps(event) + "\n", encoding="utf-8"
    )
    assert import_repo(repo) == 1
    assert import_repo(repo) == 0
    (run / "usage_events.jsonl").unlink()
    rows = list_events(repo)
    assert len(rows) == 1
    assert rows[0]["source"] == "import"
    assert rows[0]["workflow_id"] == "home"
    assert rows[0]["recorded_at"] == "2026-09-20T16:00:00Z"
    assert rows[0]["model_actual"] == "claude-sonnet"


def test_runner_event_lands_in_the_database(tmp_path: Path):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "run_id": "r1",
                "workflow_id": "smoke",
                "state": "running",
                "started_at": "2026-10-10T00:00:00Z",
                "updated_at": "2026-10-10T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    step = StepSpec(
        id="step1", agent="cursor", model="composer-2", prompt_file="p.md"
    )
    result = AdapterResult(
        exit_code=0,
        session_id="sess",
        model_actual="Composer 2.5",
        input_uncached=1,
        cache_read=0,
        cache_write=0,
        output=2,
        cost_usd=1.5,
        dirty=False,
        stdout="",
        stderr="",
    )
    _write_event(run_dir, run_id="r1", step=step, result=result)
    rows = list_events(tmp_path)
    assert len(rows) == 1
    assert rows[0]["source"] == "run"
    assert rows[0]["workflow_id"] == "smoke"
    assert rows[0]["session_id"] == "sess"
    assert rows[0]["output"] == 2
    assert (run_dir / "usage_events.jsonl").is_file()
