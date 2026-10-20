from pathlib import Path

import pytest

from aiwork.adapters.base import AdapterResult
from aiwork.models import StepSpec, WorkflowSpec
from aiwork.pause import pause_problem
from aiwork.runner import RunnerError, run_workflow
from aiwork.status_store import get_current, read_status


def _wf(tmp_path: Path, *, max_retries: int = 2) -> WorkflowSpec:
    prompt = tmp_path / "p.md"
    prompt.write_text("do the task", encoding="utf-8")
    brief = tmp_path / "b.md"
    brief.write_text("brief", encoding="utf-8")
    nxt = tmp_path / "n.md"
    nxt.write_text("next", encoding="utf-8")
    return WorkflowSpec(
        id="demo",
        brief_path=str(brief),
        steps=[
            StepSpec(
                id="a",
                agent="cursor",
                model="m",
                prompt_file=str(prompt),
                max_retries=max_retries,
                test_command='python -c "import sys; sys.exit(0)"',
            ),
            StepSpec(
                id="b",
                agent="cursor",
                model="m",
                prompt_file=str(nxt),
                test_command='python -c "import sys; sys.exit(0)"',
            ),
        ],
    )


def _result(code: int, stdout: str = "", stderr: str = "") -> AdapterResult:
    return AdapterResult(code, "s", "m", 1, 0, 0, 1, None, False, stdout, stderr)


def test_used_up_allowance_waits_and_does_not_continue(tmp_path: Path):
    calls: list[str] = []

    def run_fn(**kwargs):
        calls.append(kwargs["step"].id)
        return _result(1, stderr="You've hit your usage limit. Enable pay-as-you-go to continue")

    run_dir = run_workflow(
        workflow=_wf(tmp_path),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    status = read_status(run_dir)
    assert status.state == "waiting"
    assert status.step_id == "a"
    assert status.last_error is not None
    assert status.last_error.startswith("月費額度已用完：不改走 pay-as-you-go。")
    assert calls == ["a"]
    assert pause_problem("must switch to pay-as-you-go") is not None


def test_login_waits_and_does_not_retry(tmp_path: Path):
    calls: list[str] = []

    def run_fn(**kwargs):
        calls.append(kwargs["step"].id)
        return _result(1, stderr="Please log in with agent login")

    run_dir = run_workflow(
        workflow=_wf(tmp_path),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    status = read_status(run_dir)
    assert status.state == "waiting"
    assert status.step_id == "a"
    assert status.last_error is not None
    assert status.last_error.startswith("未登入：")
    assert "Please log in" in status.last_error
    assert calls == ["a"]
    assert not (run_dir / "steps" / "a" / "ok").exists()
    assert get_current(tmp_path / "runs") == run_dir.name
    with pytest.raises(RunnerError, match="already"):
        run_workflow(
            workflow=_wf(tmp_path),
            runs_root=tmp_path / "runs",
            workdir=tmp_path,
            root=tmp_path,
            adapters={"cursor": run_fn},
        )


def test_permission_waits(tmp_path: Path):
    def run_fn(**kwargs):
        return _result(1, stderr="permission denied: workspace")

    run_dir = run_workflow(
        workflow=_wf(tmp_path, max_retries=0),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    status = read_status(run_dir)
    assert status.state == "waiting"
    assert status.last_error is not None
    assert status.last_error.startswith("權限不足：")


def test_resume_continues_same_run_from_paused_step(tmp_path: Path):
    calls: list[str] = []
    hits = {"b": 0}

    def run_fn(**kwargs):
        step_id = kwargs["step"].id
        calls.append(step_id)
        if step_id == "a":
            return _result(0)
        hits["b"] += 1
        if hits["b"] == 1:
            return _result(1, stderr="Please log in")
        return _result(0)

    run_dir = run_workflow(
        workflow=_wf(tmp_path),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    assert read_status(run_dir).state == "waiting"
    assert calls == ["a", "b"]
    run_dir2 = run_workflow(
        workflow=_wf(tmp_path),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
        resume_run_id=run_dir.name,
    )
    assert run_dir2 == run_dir
    assert calls == ["a", "b", "b"]
    assert read_status(run_dir2).state == "succeeded"


def test_product_decision_waits_even_when_exit_ok(tmp_path: Path):
    calls: list[str] = []

    def run_fn(**kwargs):
        calls.append(kwargs["step"].id)
        return _result(0, stdout="需要產品決定：要保留舊 API 嗎")

    run_dir = run_workflow(
        workflow=_wf(tmp_path),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    status = read_status(run_dir)
    assert status.state == "waiting"
    assert status.last_error is not None
    assert status.last_error.startswith("需要產品決定：")
    assert calls == ["a"]
