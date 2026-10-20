from pathlib import Path

import pytest

from aiwork.adapters.base import AdapterResult
from aiwork.models import StepSpec, WorkflowSpec
from aiwork.runner import RunnerError, run_workflow
from aiwork.status_store import get_current, read_status


def test_adapter_exception_marks_failed_and_clears_current(tmp_path: Path):
    brief = tmp_path / "b.md"
    brief.write_text("b", encoding="utf-8")
    p1 = tmp_path / "p1.md"
    p1.write_text("one", encoding="utf-8")
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
            )
        ],
    )

    def boom(**kwargs):
        raise RuntimeError("cli missing")

    runs = tmp_path / "runs"
    run_dir = run_workflow(
        workflow=wf,
        runs_root=runs,
        workdir=tmp_path,
        root=tmp_path,
        adapters={"cursor": boom},
    )
    assert read_status(run_dir).state == "failed"
    assert get_current(runs) is None


def test_run_rejects_unknown_profile_before_any_step(tmp_path: Path):
    from aiwork.cli import _build_adapters
    from aiwork.workflow import load_workflow
    import yaml

    brief = tmp_path / "briefs" / "t.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("x", encoding="utf-8")
    prompt = tmp_path / "prompts" / "t.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("hi", encoding="utf-8")
    (tmp_path / "mcp-profiles").mkdir()
    (tmp_path / "mcp-profiles" / "default.yaml").write_text("id: default\nservers: []\n", encoding="utf-8")
    wf_path = tmp_path / "workflows" / "t.yaml"
    wf_path.parent.mkdir(parents=True)
    wf_path.write_text(
        yaml.safe_dump(
            {
                "id": "t",
                "brief_path": "briefs/t.md",
                "steps": [
                    {
                        "id": "a",
                        "agent": "cursor",
                        "model": "m",
                        "prompt_file": "prompts/t.md",
                        "mcp_profile": "does-not-exist",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    from aiwork.profiles import ProfileError, validate_workflow_profiles

    spec = load_workflow(wf_path, root=tmp_path)
    with pytest.raises(ProfileError):
        validate_workflow_profiles(tmp_path, spec)
