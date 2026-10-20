from pathlib import Path

from aiwork.adapters.base import AdapterResult
from aiwork.models import StepSpec, WorkflowSpec
from aiwork.runner import run_workflow
from aiwork.status_store import get_current, read_status, set_current, write_status
from aiwork.models import RunStatus
from datetime import datetime, timezone


def _wf(tmp_path: Path, *, approval_second: bool = False) -> WorkflowSpec:
    brief = tmp_path / "b.md"
    brief.write_text("brief", encoding="utf-8")
    p1 = tmp_path / "p1.md"
    p2 = tmp_path / "p2.md"
    p1.write_text("one", encoding="utf-8")
    p2.write_text("two", encoding="utf-8")
    return WorkflowSpec(
        id="demo",
        brief_path=str(brief),
        steps=[
            StepSpec(
                id="a",
                agent="cursor",
                model="m",
                prompt_file=str(p1),
                test_command='python -c "import sys; sys.exit(0)"',
            ),
            StepSpec(
                id="b",
                agent="cursor",
                model="m",
                prompt_file=str(p2),
                approval=approval_second,
                test_command='python -c "import sys; sys.exit(0)"',
            ),
        ],
    )


def test_sequential_stops_on_failure(tmp_path: Path):
    calls: list[str] = []

    def run_fn(**kwargs):
        calls.append(kwargs["prompt"])
        return AdapterResult(1, "s", "m", 1, 0, 0, 1, None, False, "", "err")

    wf = _wf(tmp_path)
    run_dir = run_workflow(
        workflow=wf,
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    assert read_status(run_dir).state == "failed"
    assert calls == ["one"]


def test_approval_gate_does_not_spawn_until_approved(tmp_path: Path):
    calls: list[str] = []

    def run_fn(**kwargs):
        calls.append(kwargs["prompt"])
        return AdapterResult(0, "s", "m", 1, 0, 0, 1, None, False, "", "")

    wf = _wf(tmp_path, approval_second=True)
    run_dir = run_workflow(
        workflow=wf,
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    assert read_status(run_dir).state == "awaiting_approval"
    assert calls == ["one"]
    # approve and resume
    approve_path = run_dir / "approvals" / "b.approved"
    approve_path.parent.mkdir(parents=True, exist_ok=True)
    approve_path.write_text("ok", encoding="utf-8")
    run_dir2 = run_workflow(
        workflow=wf,
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
        resume_run_id=run_dir.name,
    )
    assert read_status(run_dir2).state == "succeeded"
    assert calls == ["one", "two"]


def test_reject_second_run_while_current_running(tmp_path: Path):
    runs = tmp_path / "runs"
    runs.mkdir()
    now = datetime.now(timezone.utc).isoformat()
    write_status(
        runs / "busy",
        RunStatus(
            run_id="busy",
            workflow_id="x",
            state="running",
            step_id="a",
            started_at=now,
            updated_at=now,
        ),
    )
    set_current(runs, "busy")
    wf = _wf(tmp_path)

    def run_fn(**kwargs):
        return AdapterResult(0, "s", "m", 0, 0, 0, 0, None, False, "", "")

    import pytest
    from aiwork.runner import RunnerError

    with pytest.raises(RunnerError, match="already"):
        run_workflow(
            workflow=wf,
            runs_root=runs,
            workdir=tmp_path,
            root=tmp_path,
            adapters={"cursor": run_fn},
        )
    assert get_current(runs) == "busy"
