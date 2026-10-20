import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from aiwork.models import StepSpec, WorkflowSpec


def test_step_spec_choice_only_role():
    step = StepSpec(id="s1", role="builder", prompt_file="p.md")
    assert step.role == "builder"
    assert step.agent is None
    assert step.model is None


def test_step_spec_choice_only_agent_and_model():
    step = StepSpec(id="s2", agent="cursor", model="composer-2.5", prompt_file="p.md")
    assert step.role is None
    assert step.agent == "cursor"
    assert step.model == "composer-2.5"


def test_step_spec_both_role_and_agent_model_rejected():
    with pytest.raises(ValidationError) as exc:
        StepSpec(id="s_both", role="builder", agent="cursor", model="composer-2.5", prompt_file="p.md")
    assert "s_both" in str(exc.value)
    assert "cannot specify both role and agent/model" in str(exc.value)


def test_step_spec_neither_role_nor_agent_model_rejected():
    with pytest.raises(ValidationError) as exc:
        StepSpec(id="s_none", prompt_file="p.md")
    assert "s_none" in str(exc.value)
    assert "must specify either role or both agent and model" in str(exc.value)


def test_step_spec_invalid_role_id():
    with pytest.raises(ValidationError) as exc:
        StepSpec(id="s_bad_role", role="Invalid_Role!", prompt_file="p.md")
    assert "s_bad_role" in str(exc.value)


def test_load_roles_unknown_field_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from aiwork.dispatch import DispatchError, load_roles

    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        """
version: 1
roles:
  builder:
    agent: gemini
    model: gemini-3.8-flash-high
    description: good builder
    account: personal
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    with pytest.raises(DispatchError) as exc:
        load_roles()
    assert "account" in str(exc.value)
    assert "不認得" in str(exc.value) or "unknown" in str(exc.value).lower()


def test_effort_three_layer_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from aiwork.dispatch import load_roles, resolve_workflow

    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        """
version: 1
roles:
  builder-high:
    agent: gemini
    model: gemini-3.8-flash-high
    effort: high
    description: role with high effort
  builder-default:
    agent: gemini
    model: gemini-3.8-flash-high
    description: role without effort
""",
        encoding="utf-8",
    )
    models_file = tmp_path / "models.yaml"
    models_file.write_text(
        """
version: 1
models:
  gemini:
    - id: gemini-3.8-flash-high
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))

    # Case 1: Step explicitly sets effort -> step wins
    step1 = StepSpec(id="s1", role="builder-high", effort="low", prompt_file="p1.md")
    # Case 2: Step doesn't set effort, role has effort -> role wins
    step2 = StepSpec(id="s2", role="builder-high", prompt_file="p2.md")
    # Case 3: Step doesn't set effort, role doesn't have effort -> default medium
    step3 = StepSpec(id="s3", role="builder-default", prompt_file="p3.md")

    wf = WorkflowSpec(id="wf_effort", brief_path="b.md", steps=[step1, step2, step3])
    resolved = resolve_workflow(wf, cli_checker=lambda _: True)

    assert resolved.steps["s1"].effort == "low"
    assert resolved.steps["s2"].effort == "high"
    assert resolved.steps["s3"].effort == "medium"


def test_batch_errors_e3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from aiwork.dispatch import DispatchError, resolve_workflow

    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        """
version: 1
roles:
  builder:
    agent: gemini
    model: gemini-3.8-flash-high
    description: good builder
""",
        encoding="utf-8",
    )
    models_file = tmp_path / "models.yaml"
    models_file.write_text(
        """
version: 1
models:
  gemini:
    - id: gemini-3.8-flash-high
  cursor:
    - id: composer-2.5
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))

    # A workflow with 4 errors at once:
    # 1. unknown role
    # 2. codex agent
    # 3. model not in catalog
    # 4. CLI not in PATH
    s1 = StepSpec(id="s1_unknown_role", role="non-existent", prompt_file="p1.md")
    s2 = StepSpec(id="s2_codex", agent="codex", model="gpt-5", prompt_file="p2.md")
    s3 = StepSpec(id="s3_bad_model", agent="cursor", model="unlisted-model-x", prompt_file="p3.md")
    s4 = StepSpec(id="s4_missing_cli", role="builder", prompt_file="p4.md")

    wf = WorkflowSpec(id="wf_errors", brief_path="b.md", steps=[s1, s2, s3, s4])

    def fake_cli_checker(name: str) -> bool:
        # Pretend agy (for builder) is missing from PATH
        if name == "agy":
            return False
        return True

    with pytest.raises(DispatchError) as exc:
        resolve_workflow(wf, cli_checker=fake_cli_checker)

    err_text = str(exc.value)
    assert "s1_unknown_role" in err_text and "non-existent" in err_text
    assert "s2_codex" in err_text and "codex 未啟用" in err_text
    assert "s3_bad_model" in err_text and "unlisted-model-x" in err_text
    assert "s4_missing_cli" in err_text and "agy" in err_text


def test_local_roles_override_and_addition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from aiwork.dispatch import load_roles

    roles_shared = tmp_path / "roles.yaml"
    roles_shared.write_text(
        """
version: 1
roles:
  builder:
    agent: gemini
    model: gemini-3.8-flash-high
    description: shared builder
  writer:
    agent: cursor
    model: composer-2.5
    description: shared writer
""",
        encoding="utf-8",
    )

    aiwork_home = tmp_path / ".aiwork"
    aiwork_home.mkdir(parents=True, exist_ok=True)

    roles_local = aiwork_home / "roles.local.yaml"
    roles_local.write_text(
        """
version: 1
roles:
  builder:
    agent: cursor
    model: composer-2.5
    description: local builder override
  planner:
    agent: claude
    model: claude-opus-5-5
    description: local only planner
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("AIWORK_ROLES", str(roles_shared))
    monkeypatch.setenv("AIWORK_HOME", str(aiwork_home))

    roles, meta = load_roles()
    assert roles["builder"].source == "local"
    assert roles["builder"].description == "local builder override"
    assert roles["builder"].agent == "cursor"

    assert roles["writer"].source == "shared"
    assert roles["writer"].description == "shared writer"

    assert roles["planner"].source == "local"
    assert roles["planner"].description == "local only planner"


def test_resolved_json_roundtrip(tmp_path: Path):
    from aiwork.dispatch import (
        ResolvedStep,
        ResolvedWorkflow,
        TableMetadata,
        load_resolved,
        save_resolved,
    )

    run_dir = tmp_path / "run_01"
    run_dir.mkdir(parents=True)

    resolved = ResolvedWorkflow(
        version=1,
        resolved_at="2026-10-17T00:00:00Z",
        tables={
            "roles": TableMetadata(path="/path/to/roles.yaml", sha256="abc123"),
            "models": TableMetadata(path="/path/to/models.yaml", sha256="def456"),
        },
        steps={
            "s1": ResolvedStep(
                step_id="s1",
                role="builder",
                agent="gemini",
                model="gemini-3.8-flash-high",
                effort="high",
                source="shared",
            ),
            "s2": ResolvedStep(
                step_id="s2",
                role=None,
                agent="cursor",
                model="composer-2.5",
                effort="medium",
                source="explicit",
            ),
        },
    )

    saved_path = save_resolved(run_dir, resolved)
    assert saved_path.is_file()
    assert not (run_dir / "resolved.json.tmp").exists()

    loaded = load_resolved(run_dir)
    assert loaded.version == 1
    assert loaded.resolved_at == "2026-10-17T00:00:00Z"
    assert loaded.steps["s1"].role == "builder"
    assert loaded.steps["s1"].agent == "gemini"
    assert loaded.steps["s1"].source == "shared"
    assert loaded.steps["s2"].source == "explicit"
