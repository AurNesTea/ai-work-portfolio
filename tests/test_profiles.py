from pathlib import Path

import pytest
import yaml

from aiwork.models import StepSpec, WorkflowSpec
from aiwork.profiles import ProfileError, resolve_profile, validate_workflow_profiles


def test_unknown_profile_fails(tmp_path: Path):
    with pytest.raises(ProfileError, match="unknown mcp_profile"):
        resolve_profile(root=tmp_path, mcp_profile="nope", skills=[])


def test_known_profile_and_skills(tmp_path: Path):
    (tmp_path / "mcp-profiles").mkdir()
    (tmp_path / "mcp-profiles" / "read-only.yaml").write_text(
        yaml.safe_dump({"id": "read-only", "servers": [{"name": "notion"}]}),
        encoding="utf-8",
    )
    pack = tmp_path / "skills" / "research"
    pack.mkdir(parents=True)
    (pack / "SKILL.md").write_text("# research\n", encoding="utf-8")
    resolved = resolve_profile(
        root=tmp_path, mcp_profile="read-only", skills=["research"]
    )
    assert resolved.mcp_config_path is not None
    assert resolved.env["AIWORK_MCP_PROFILE"] == "read-only"
    assert resolved.skill_paths == [pack]


def test_validate_ignores_skill_names(tmp_path: Path):
    (tmp_path / "mcp-profiles").mkdir()
    (tmp_path / "mcp-profiles" / "default.yaml").write_text(
        yaml.safe_dump({"id": "default", "servers": []}),
        encoding="utf-8",
    )
    spec = WorkflowSpec(
        id="t",
        brief_path="briefs/t.md",
        steps=[
            StepSpec(
                id="a",
                agent="cursor",
                model="m",
                prompt_file="prompts/t.md",
                skills=["not-a-real-pack"],
            )
        ],
    )
    validate_workflow_profiles(tmp_path, spec)
