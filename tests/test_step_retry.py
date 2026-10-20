from pathlib import Path

from aiwork.adapters.base import AdapterResult
from aiwork.ledger import read_usage
from aiwork.models import StepSpec, WorkflowSpec
from aiwork.runner import run_workflow
from aiwork.status_store import read_status


def _wf(tmp_path: Path, *, max_retries: int) -> WorkflowSpec:
    prompt = tmp_path / "p.md"
    prompt.write_text("fix the build", encoding="utf-8")
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


def _fail(stderr: str) -> AdapterResult:
    return AdapterResult(1, "s", "m", 1, 0, 0, 1, None, False, "out", stderr)


def _ok() -> AdapterResult:
    return AdapterResult(0, "s", "m", 1, 0, 0, 1, None, False, "done", "")


def test_retry_passes_previous_error_then_continues(tmp_path: Path):
    prompts: list[str] = []

    def run_fn(**kwargs):
        prompts.append(kwargs["prompt"])
        if kwargs["step"].id == "b":
            return _ok()
        if len([p for p in prompts if "fix the build" in p]) == 1:
            return _fail("compile error")
        return _ok()

    run_dir = run_workflow(
        workflow=_wf(tmp_path, max_retries=1),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    assert prompts[0] == "fix the build"
    assert prompts[1] == "fix the build\n\n上一輪錯誤：\ncompile error"
    assert prompts[2] == "next"
    assert read_status(run_dir).state == "succeeded"
    assert len(read_usage(run_dir)) == 3


def test_stops_when_retries_are_exhausted(tmp_path: Path):
    prompts: list[str] = []

    def run_fn(**kwargs):
        prompts.append(kwargs["prompt"])
        return _fail("still broken")

    run_dir = run_workflow(
        workflow=_wf(tmp_path, max_retries=1),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    status = read_status(run_dir)
    assert status.state == "failed"
    assert status.step_id == "a"
    assert status.last_error == "still broken"
    assert prompts == [
        "fix the build",
        "fix the build\n\n上一輪錯誤：\nstill broken",
    ]
    assert len(read_usage(run_dir)) == 2
