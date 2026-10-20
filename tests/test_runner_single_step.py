from pathlib import Path

from aiwork.adapters.base import AdapterResult
from aiwork.ledger import read_usage
from aiwork.models import StepSpec
from aiwork.runner import run_single_step
from aiwork.status_store import read_status


def test_single_step_writes_status_and_usage(tmp_path: Path):
    prompt = tmp_path / "p.md"
    prompt.write_text("do thing", encoding="utf-8")
    step = StepSpec(
        id="s1", agent="cursor", model="composer-2", prompt_file=str(prompt)
    )

    def fake_run(**kwargs):
        return AdapterResult(
            0, "sess", "Composer 2", 1, 0, 0, 2, None, False, "", ""
        )

    run_dir = run_single_step(
        runs_root=tmp_path / "runs",
        workflow_id="demo",
        step=step,
        workdir=tmp_path,
        run_fn=fake_run,
    )
    assert read_status(run_dir).state == "succeeded"
    ev = read_usage(run_dir)[0]
    # normalize: "Composer 2" → "composer-2" matches requested
    assert ev.mismatch is False
    assert ev.input_uncached == 1
    assert ev.output == 2


def test_mismatch_when_unrelated_models(tmp_path: Path):
    prompt = tmp_path / "p.md"
    prompt.write_text("do thing", encoding="utf-8")
    step = StepSpec(
        id="s1", agent="cursor", model="composer-2", prompt_file=str(prompt)
    )

    def fake_run(**kwargs):
        return AdapterResult(0, "sess", "gpt-5", 1, 0, 0, 2, None, False, "", "")

    run_dir = run_single_step(
        runs_root=tmp_path / "runs",
        workflow_id="demo",
        step=step,
        workdir=tmp_path,
        run_fn=fake_run,
    )
    assert read_usage(run_dir)[0].mismatch is True


def test_mismatch_version_suffix(tmp_path: Path):
    prompt = tmp_path / "p.md"
    prompt.write_text("do thing", encoding="utf-8")
    step = StepSpec(
        id="s1", agent="cursor", model="composer-2", prompt_file=str(prompt)
    )

    def fake_run(**kwargs):
        return AdapterResult(0, "sess", "composer-2.5", 1, 0, 0, 2, None, False, "", "")

    run_dir = run_single_step(
        runs_root=tmp_path / "runs",
        workflow_id="demo",
        step=step,
        workdir=tmp_path,
        run_fn=fake_run,
    )
    assert read_usage(run_dir)[0].mismatch is True
