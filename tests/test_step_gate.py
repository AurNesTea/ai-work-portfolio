from pathlib import Path

import pytest

from aiwork.adapters.base import AdapterResult
from aiwork.models import StepSpec, WorkflowSpec
from aiwork.runner import RunnerError, run_workflow
from aiwork.status_store import read_status

_PASS = 'python -c "import sys; sys.exit(0)"'
_FAIL = 'python -c "import sys; sys.exit(1)"'


def _step(tmp_path: Path, step_id: str, prompt: str, *, test_command: str, max_retries: int = 0) -> StepSpec:
    path = tmp_path / f"{step_id}.md"
    path.write_text(prompt, encoding="utf-8")
    return StepSpec(
        id=step_id,
        agent="cursor",
        model="m",
        prompt_file=str(path),
        max_retries=max_retries,
        test_command=test_command,
    )


def _wf(tmp_path: Path, steps: list[StepSpec]) -> WorkflowSpec:
    brief = tmp_path / "b.md"
    brief.write_text("brief", encoding="utf-8")
    return WorkflowSpec(id="demo", brief_path=str(brief), steps=steps)


def _ok() -> AdapterResult:
    return AdapterResult(0, "s", "m", 1, 0, 0, 1, None, False, "done", "")


def _dev_fail() -> AdapterResult:
    return AdapterResult(1, "s", "m", 1, 0, 0, 1, None, False, "", "compile error")


def test_missing_test_command_does_not_start(tmp_path: Path):
    step = _step(tmp_path, "a", "build", test_command="   ")
    with pytest.raises(RunnerError, match="a"):
        run_workflow(
            workflow=_wf(tmp_path, [step]),
            runs_root=tmp_path / "runs",
            workdir=tmp_path,
            root=tmp_path,
            adapters={"cursor": lambda **_kwargs: _ok()},
        )
    assert not (tmp_path / "runs").exists()


def test_dev_failure_skips_test_and_spends_a_life(tmp_path: Path):
    marker = tmp_path / "test-ran"
    script = tmp_path / "mark_test.py"
    script.write_text(f"open(r'{marker}', 'w', encoding='utf-8').write('x')\n", encoding="utf-8")
    calls: list[str] = []

    def run_fn(**kwargs):
        calls.append(kwargs["prompt"])
        return _dev_fail()

    run_dir = run_workflow(
        workflow=_wf(
            tmp_path,
            [_step(tmp_path, "a", "build", test_command=f'python "{script}"', max_retries=1)],
        ),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    status = read_status(run_dir)
    assert status.state == "failed"
    assert status.lives_total == 2
    assert status.lives_left == 0
    assert not marker.exists()
    assert "compile error" in calls[1]


def test_red_test_spends_a_life_and_returns_output(tmp_path: Path):
    prompts: list[str] = []

    def run_fn(**kwargs):
        prompts.append(kwargs["prompt"])
        return _ok()

    run_dir = run_workflow(
        workflow=_wf(
            tmp_path,
            [_step(tmp_path, "a", "build", test_command=_FAIL, max_retries=0)],
        ),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    status = read_status(run_dir)
    assert status.state == "failed"
    assert status.lives_total == 1
    assert status.lives_left == 0
    assert len(prompts) == 1


def test_dev_and_test_pass_clears_and_resets_next_lives(tmp_path: Path):
    def run_fn(**_kwargs):
        return _ok()

    run_dir = run_workflow(
        workflow=_wf(
            tmp_path,
            [
                _step(tmp_path, "a", "build", test_command=_PASS, max_retries=2),
                _step(tmp_path, "b", "next", test_command=_PASS, max_retries=0),
            ],
        ),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    status = read_status(run_dir)
    assert status.state == "succeeded"
    assert status.step_id == "b"
    assert status.lives_total == 1
    assert status.lives_left == 1


def test_pause_does_not_spend_a_life_or_run_test(tmp_path: Path):
    marker = tmp_path / "test-ran"
    script = tmp_path / "mark_pause.py"
    script.write_text(f"open(r'{marker}', 'w', encoding='utf-8').write('x')\n", encoding="utf-8")

    def run_fn(**_kwargs):
        return AdapterResult(
            1, "s", "m", 1, 0, 0, 1, None, False, "", "usage limit reached"
        )

    run_dir = run_workflow(
        workflow=_wf(
            tmp_path,
            [
                _step(
                    tmp_path,
                    "a",
                    "build",
                    test_command=f'python "{script}"',
                    max_retries=2,
                )
            ],
        ),
        runs_root=tmp_path / "runs",
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
    )
    status = read_status(run_dir)
    assert status.state == "waiting"
    assert status.lives_total == 3
    assert status.lives_left == 3
    assert not marker.exists()
