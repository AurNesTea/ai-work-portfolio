from pathlib import Path

import pytest
import yaml

from aiwork.models import WorkflowSpec
from aiwork.workflow import WorkflowError, load_workflow


def _write_minimal(tmp_path: Path) -> Path:
    brief = tmp_path / "briefs" / "smoke.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("# smoke\n", encoding="utf-8")
    prompt = tmp_path / "prompts" / "smoke" / "step1.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("hello", encoding="utf-8")
    wf = {
        "id": "smoke",
        "brief_path": str(brief.relative_to(tmp_path)).replace("\\", "/"),
        "trigger": "manual",
        "steps": [
            {
                "id": "step1",
                "agent": "cursor",
                "model": "composer-2",
                "prompt_file": str(prompt.relative_to(tmp_path)).replace("\\", "/"),
            }
        ],
    }
    path = tmp_path / "workflows" / "smoke.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(wf), encoding="utf-8")
    return path


def test_load_workflow_ok(tmp_path: Path):
    path = _write_minimal(tmp_path)
    spec = load_workflow(path, root=tmp_path)
    assert isinstance(spec, WorkflowSpec)
    assert spec.steps[0].id == "step1"


def test_load_workflow_missing_brief_raises(tmp_path: Path):
    path = _write_minimal(tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["brief_path"] = "briefs/missing.md"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(WorkflowError, match="brief"):
        load_workflow(path, root=tmp_path)
