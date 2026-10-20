from pathlib import Path

from aiwork.adapters.base import AdapterResult
from aiwork.models import StepSpec, WorkflowSpec
from aiwork.runner import run_workflow
from aiwork.status_store import read_status


def test_resume_retries_failed_step_not_skips(tmp_path: Path):
    brief = tmp_path / "b.md"
    brief.write_text("b", encoding="utf-8")
    p1 = tmp_path / "p1.md"
    p2 = tmp_path / "p2.md"
    p1.write_text("one", encoding="utf-8")
    p2.write_text("two", encoding="utf-8")
    wf = WorkflowSpec(
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
                test_command='python -c "import sys; sys.exit(0)"',
            ),
        ],
    )
    calls: list[str] = []

    def run_fn(**kwargs):
        calls.append(kwargs["prompt"])
        # first attempt at "one" fails; later attempts succeed
        if kwargs["prompt"] == "one" and calls.count("one") == 1:
            return AdapterResult(3, "s", "m", 1, 0, 0, 1, None, False, "fail-out", "err")
        return AdapterResult(0, "s", "m", 1, 0, 0, 1, None, False, "ok", "")

    runs = tmp_path / "runs"
    run_dir = run_workflow(
        workflow=wf,
        runs_root=runs,
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    assert read_status(run_dir).state == "failed"
    assert calls == ["one"]

    run_dir2 = run_workflow(
        workflow=wf,
        runs_root=runs,
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
        resume_run_id=run_dir.name,
    )
    assert calls == ["one", "one", "two"]
    assert read_status(run_dir2).state == "succeeded"
