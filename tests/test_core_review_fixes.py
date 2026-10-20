"""Regressions from the branch review: cancel pointer, id sinks, prompt read, resume dirty."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aiwork.adapters.base import AdapterResult
from aiwork.cli import app
from aiwork.models import RunStatus, StepSpec, WorkflowSpec
from aiwork.runner import RunnerError, _resolve_prompt, run_workflow
from aiwork.status_store import get_current, read_status, set_current, write_status

PASS = 'python -c "import sys; sys.exit(0)"'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status(run_id: str, state: str = "succeeded") -> RunStatus:
    return RunStatus(
        run_id=run_id, workflow_id="w", state=state, started_at=_now(), updated_at=_now()
    )


def _ok(**kwargs) -> AdapterResult:
    return AdapterResult(0, "s", "m", 1, 0, 0, 1, None, False, "ok", "")


def test_cancelling_an_old_run_keeps_the_live_current_pointer(tmp_path: Path):
    runs = tmp_path / "runs"
    write_status(runs / "old1", _status("old1"))
    write_status(runs / "live2", _status("live2", "running"))
    set_current(runs, "live2")

    result = CliRunner().invoke(app, ["cancel", "old1", "--runs-root", str(runs)])

    assert result.exit_code == 0, result.output
    assert read_status(runs / "old1").state == "cancelled"
    assert get_current(runs) == "live2"

    result = CliRunner().invoke(app, ["cancel", "live2", "--runs-root", str(runs)])
    assert result.exit_code == 0, result.output
    assert get_current(runs) is None


@pytest.mark.parametrize(
    "run_id,step_id",
    [
        ("r1", "..\\..\\..\\escape"),
        ("r1", "../../escape"),
        ("..", "step"),
        ("r1", ".."),
        ("a/b", "step"),
        ("r1", ""),
    ],
)
def test_approve_refuses_ids_that_climb_out_of_runs(tmp_path: Path, run_id, step_id):
    runs = tmp_path / "sandbox" / "runs"
    runs.mkdir(parents=True)

    result = CliRunner().invoke(app, ["approve", run_id, step_id, "--runs-root", str(runs)])

    assert result.exit_code != 0
    assert list(tmp_path.rglob("*.approved")) == []


def test_approve_still_writes_for_a_normal_id(tmp_path: Path):
    runs = tmp_path / "runs"
    result = CliRunner().invoke(
        app, ["approve", "8af1029f6dd6", "model-claude-installer", "--runs-root", str(runs)]
    )
    assert result.exit_code == 0, result.output
    assert (runs / "8af1029f6dd6" / "approvals" / "model-claude-installer.approved").is_file()


def test_resume_refuses_a_run_id_that_climbs_out(tmp_path: Path):
    wf = tmp_path / "wf.yaml"
    wf.write_text("id: w\nbrief_path: b.md\nsteps: []\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["run", str(wf), "--resume", "..", "--root", str(tmp_path)])
    assert result.exit_code == 2


def test_unreadable_prompt_ends_the_run_failed_and_frees_current(tmp_path: Path):
    wf = WorkflowSpec(
        id="demo",
        brief_path=str(tmp_path / "b.md"),
        steps=[
            StepSpec(
                id="a",
                agent="cursor",
                model="m",
                prompt_file="does-not-exist.md",
                test_command=PASS,
            )
        ],
    )
    runs = tmp_path / "runs"

    with pytest.raises(RunnerError, match="cannot read prompt"):
        run_workflow(
            workflow=wf, runs_root=runs, workdir=tmp_path, root=tmp_path, adapters={"cursor": _ok}
        )

    (run_dir,) = [p for p in runs.iterdir() if p.is_dir()]
    status = read_status(run_dir)
    assert status.state == "failed"
    assert "does-not-exist.md" in (status.last_error or "")
    assert get_current(runs) is None  # a stuck "running" run would block every later run


def test_resumed_run_keeps_the_dirty_flag_from_its_earlier_steps(tmp_path: Path):
    for name in ("p1", "p2"):
        (tmp_path / f"{name}.md").write_text(name, encoding="utf-8")
    wf = WorkflowSpec(
        id="demo",
        brief_path=str(tmp_path / "b.md"),
        steps=[
            StepSpec(id="a", agent="cursor", model="m", prompt_file=str(tmp_path / "p1.md"), test_command=PASS),
            StepSpec(id="b", agent="cursor", model="m", prompt_file=str(tmp_path / "p2.md"), test_command=PASS),
        ],
    )
    calls: list[str] = []

    def run_fn(**kwargs):
        calls.append(kwargs["prompt"])
        if kwargs["prompt"] == "p1":
            return AdapterResult(0, "s", "m", 1, 0, 0, 1, None, True, "ok", "")  # dirty usage
        if calls.count("p2") == 1:
            return AdapterResult(3, "s", "m", 1, 0, 0, 1, None, False, "", "boom")
        return AdapterResult(0, "s", "m", 1, 0, 0, 1, None, False, "ok", "")

    runs = tmp_path / "runs"
    first = run_workflow(
        workflow=wf, runs_root=runs, workdir=tmp_path, root=tmp_path, adapters={"cursor": run_fn}
    )
    assert read_status(first).state == "failed"
    assert read_status(first).dirty is True

    resumed = run_workflow(
        workflow=wf,
        runs_root=runs,
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": run_fn},
        resume_run_id=first.name,
    )
    final = read_status(resumed)
    assert final.state == "succeeded"
    assert final.dirty is True


def test_prompt_lookup_prefers_the_root_over_the_cwd(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    other = tmp_path / "other-project"
    for base, text in ((root, "ROOT PROMPT"), (other, "LOCAL PROMPT")):
        (base / "prompts").mkdir(parents=True)
        (base / "prompts" / "a.md").write_text(text, encoding="utf-8")
    monkeypatch.chdir(other)
    step = StepSpec(id="a", agent="cursor", model="m", prompt_file="prompts/a.md", test_command=PASS)

    assert _resolve_prompt(root, step) == "ROOT PROMPT"

    (root / "prompts" / "a.md").unlink()  # CWD stays a fallback when root has no such file
    assert _resolve_prompt(root, step) == "LOCAL PROMPT"
