from pathlib import Path

import yaml

from aiwork.adapters.base import AdapterResult
from aiwork.cli import _build_adapters
from aiwork.models import StepSpec


def test_run_does_not_inject_skill_paths(tmp_path: Path, monkeypatch):
    (tmp_path / "mcp-profiles").mkdir()
    (tmp_path / "mcp-profiles" / "default.yaml").write_text(
        yaml.safe_dump({"id": "default", "servers": []}),
        encoding="utf-8",
    )
    seen: dict[str, str] = {}

    def fake_cursor(**kwargs):
        seen["prompt"] = kwargs["prompt"]
        return AdapterResult(0, None, "m", 0, 0, 0, 0, None, False, "", "")

    monkeypatch.setattr("aiwork.cli.run_cursor", fake_cursor)
    step = StepSpec(
        id="a",
        agent="cursor",
        model="m",
        prompt_file="prompts/t.md",
        skills=["research"],
    )
    _build_adapters(tmp_path)["cursor"](
        step=step,
        model="m",
        prompt="do the task",
        cwd=str(tmp_path),
        timeout_sec=5,
        run_dir=tmp_path / "run",
    )
    assert seen["prompt"] == "do the task"
