from __future__ import annotations

import json
from pathlib import Path
import pytest
from typer.testing import CliRunner

from aiwork.adapters.base import AdapterResult
from aiwork.cli import app
from aiwork.dispatch import (
    ResolvedStep,
    ResolvedWorkflow,
    TableMetadata,
    load_resolved,
    re_resolve_run,
    resolve_workflow,
    save_resolved,
)
from aiwork.models import StepSpec, WorkflowSpec
from aiwork.packs import (
    MachineProfile,
    build_role_prompt,
    inject_role_header,
    is_valid_role_path,
    save_machine_profile,
)
from aiwork.runner import run_workflow

PASS = 'python -c "import sys; sys.exit(0)"'


def _fake_adapter(seen: list[dict], model_actual="test-model", fail_first_times=0):
    calls = 0

    def adapter(**kw):
        nonlocal calls
        seen.append(kw)
        calls += 1
        if calls <= fail_first_times:
            raise RuntimeError("simulated adapter failure")
        return AdapterResult(
            exit_code=0,
            session_id=None,
            model_actual=model_actual,
            input_uncached=10,
            cache_read=5,
            cache_write=0,
            output=20,
            cost_usd=0.01,
            dirty=False,
            stdout="ok",
            stderr="",
        )

    return adapter


def _setup_roles_and_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "mcp-profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "mcp-profiles" / "default.yaml").write_text("servers: []\n", encoding="utf-8")
    roles_file = tmp_path / "config" / "roles.yaml"
    roles_file.parent.mkdir(parents=True, exist_ok=True)
    roles_file.write_text(
        """
version: 1
roles:
  builder:
    agent: gemini
    model: gemini-3.8-flash-high
    description: good builder
  writer:
    agent: cursor
    model: composer-2.5
    description: good writer
""",
        encoding="utf-8",
    )
    models_file = tmp_path / "config" / "models.yaml"
    models_file.write_text(
        """
version: 1
models:
  gemini:
    - id: gemini-3.8-flash-high
    - id: gemini-3.8-flash-low
  cursor:
    - id: composer-2.5
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))
    return roles_file, models_file


# =====================================================================
# 1. Pure Unit Tests for inject_role_header / build_role_prompt
# =====================================================================


def test_inject_role_header_no_role_file_returns_verbatim():
    prompt = "Do some coding work.\nSecond line."
    assert inject_role_header(prompt, role_file=None, delivery=None) == prompt
    assert inject_role_header(prompt, role_file=None, delivery="none") == prompt
    assert build_role_prompt(prompt, role_file=None) == prompt


def test_inject_role_header_delivery_none_returns_verbatim():
    prompt = "Do some coding work."
    role_file = "C:/Users/<user>/.agents/agents/builder.md"
    assert inject_role_header(prompt, role_file=role_file, delivery="none") == prompt


def test_inject_role_header_valid_path_injects_header():
    prompt = "Implement the algorithm."
    role_file = "C:/Users/<user>/.agents/agents/builder.md"
    expected = (
        "@C:/Users/<user>/.agents/agents/builder.md\n"
        "請依上面這個角色檔的工作原則執行下面的任務。\n\n"
        "Implement the algorithm."
    )
    result = inject_role_header(prompt, role_file=role_file, delivery="prompt-path")
    assert result == expected

    # Also test build_role_prompt alias with Path object
    p_obj = Path("C:/Users/<user>/.agents/agents/builder.md")
    result2 = build_role_prompt(prompt, role_file=p_obj, delivery="prompt-path")
    assert result2 == expected


def test_inject_role_header_normalizes_windows_backslashes():
    prompt = "Task description."
    # Pass Windows backslash path
    role_file = r"C:/Users/<user>\.agents\agents\writer.md"
    expected = (
        "@C:/Users/<user>/.agents/agents/writer.md\n"
        "請依上面這個角色檔的工作原則執行下面的任務。\n\n"
        "Task description."
    )
    result = inject_role_header(prompt, role_file=role_file, delivery="prompt-path")
    assert result == expected


def test_inject_role_header_whitespace_path_warns_and_returns_verbatim():
    prompt = "Fix the login bug."
    bad_path = "C:/Program Files/Python312/.agents/agents/builder.md"
    with pytest.warns(UserWarning, match="whitespace"):
        result = inject_role_header(prompt, role_file=bad_path, delivery="prompt-path")
    assert result == prompt


def test_inject_role_header_non_ascii_path_warns_and_returns_verbatim():
    prompt = "Fix the login bug."
    bad_path = "C:/path/to/projects/.agents/agents/builder.md"
    with pytest.warns(UserWarning, match="invalid characters"):
        result = inject_role_header(prompt, role_file=bad_path, delivery="prompt-path")
    assert result == prompt


# =====================================================================
# 2. Step Without Role: Prompt Verbatim Unchanged
# =====================================================================


def test_step_without_role_prompt_verbatim_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _setup_roles_and_models(tmp_path, monkeypatch)

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    p_content = "This is a prompt without role.\nLine 2.\nLine 3."
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text(p_content, encoding="utf-8")

    step = StepSpec(
        id="s_norole",
        agent="cursor",
        model="composer-2.5",
        prompt_file=str(prompt_file),
        test_command=PASS,
    )
    wf = WorkflowSpec(id="wf_norole", brief_path=str(brief), steps=[step])

    seen: list[dict] = []
    adapters = {"cursor": _fake_adapter(seen, "composer-2.5")}
    runs_dir = tmp_path / "runs"

    resolved = resolve_workflow(wf, cli_checker=lambda _: True)
    assert resolved.steps["s_norole"].role is None
    assert resolved.steps["s_norole"].role_file is None
    assert resolved.steps["s_norole"].delivery == "none"

    run_dir = run_workflow(
        workflow=wf,
        runs_root=runs_dir,
        workdir=tmp_path,
        root=tmp_path,
        adapters=adapters,
        resolved=resolved,
    )

    assert len(seen) == 1
    # Prompt passed to adapter is verbatim unchanged
    assert seen[0]["prompt"] == p_content


def test_step_without_role_retry_prompt_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _setup_roles_and_models(tmp_path, monkeypatch)

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    p_content = "Retry test prompt without role."
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text(p_content, encoding="utf-8")

    step = StepSpec(
        id="s_retry",
        agent="cursor",
        model="composer-2.5",
        prompt_file=str(prompt_file),
        max_retries=1,
        test_command=PASS,
    )
    wf = WorkflowSpec(id="wf_retry", brief_path=str(brief), steps=[step])

    seen: list[dict] = []
    # Fail first attempt to trigger retry
    adapters = {"cursor": _fake_adapter(seen, "composer-2.5", fail_first_times=1)}
    runs_dir = tmp_path / "runs"

    resolved = resolve_workflow(wf, cli_checker=lambda _: True)
    run_workflow(
        workflow=wf,
        runs_root=runs_dir,
        workdir=tmp_path,
        root=tmp_path,
        adapters=adapters,
        resolved=resolved,
    )

    assert len(seen) == 2
    # 1st attempt: original prompt verbatim
    assert seen[0]["prompt"] == p_content
    # 2nd attempt: original prompt followed by retry error, NO role header
    assert seen[1]["prompt"].startswith(p_content)
    assert "@" not in seen[1]["prompt"]
    assert "上一輪錯誤：" in seen[1]["prompt"]


# =====================================================================
# 3. Step With Role: Prompt Injected When Definition Exists
# =====================================================================


def test_step_with_role_and_definition_injects_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _setup_roles_and_models(tmp_path, monkeypatch)

    user_home = tmp_path / "fake_user_home"
    agents_dir = user_home / ".agents" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    builder_md = agents_dir / "builder.md"
    builder_md.write_text(
        """---
name: builder
description: good builder
skills: []
---
1. Always follow sealed plans.
2. Verify before complete.
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_USER_HOME", str(user_home))

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    p_content = "Please write the feature implementation."
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text(p_content, encoding="utf-8")

    step = StepSpec(
        id="s_role",
        role="builder",
        prompt_file=str(prompt_file),
        max_retries=1,
        test_command=PASS,
    )
    wf = WorkflowSpec(id="wf_role", brief_path=str(brief), steps=[step])

    resolved = resolve_workflow(wf, cli_checker=lambda _: True)
    expected_posix_path = builder_md.resolve().as_posix()
    assert resolved.steps["s_role"].role == "builder"
    assert resolved.steps["s_role"].role_file == expected_posix_path
    assert resolved.steps["s_role"].delivery == "prompt-path"

    seen: list[dict] = []
    adapters = {"gemini": _fake_adapter(seen, "gemini-3.8-flash-high", fail_first_times=1)}
    runs_dir = tmp_path / "runs"

    run_dir = run_workflow(
        workflow=wf,
        runs_root=runs_dir,
        workdir=tmp_path,
        root=tmp_path,
        adapters=adapters,
        resolved=resolved,
    )

    assert len(seen) == 2
    expected_header = f"@{expected_posix_path}\n請依上面這個角色檔的工作原則執行下面的任務。\n\n"
    # First attempt: header + prompt
    assert seen[0]["prompt"] == expected_header + p_content
    # Retry attempt: header + prompt + error at bottom
    assert seen[1]["prompt"].startswith(expected_header + p_content)
    assert "上一輪錯誤：" in seen[1]["prompt"]


def test_step_with_role_no_definition_file_remains_verbatim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _setup_roles_and_models(tmp_path, monkeypatch)

    # Empty agents directory (no builder.md)
    user_home = tmp_path / "fake_user_home"
    (user_home / ".agents" / "agents").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AIWORK_USER_HOME", str(user_home))

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    p_content = "Task prompt with role but no role definition file."
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text(p_content, encoding="utf-8")

    step = StepSpec(
        id="s_nodef",
        role="builder",
        prompt_file=str(prompt_file),
        test_command=PASS,
    )
    wf = WorkflowSpec(id="wf_nodef", brief_path=str(brief), steps=[step])

    resolved = resolve_workflow(wf, cli_checker=lambda _: True)
    assert resolved.steps["s_nodef"].role == "builder"
    assert resolved.steps["s_nodef"].role_file is None
    assert resolved.steps["s_nodef"].delivery == "none"

    seen: list[dict] = []
    adapters = {"gemini": _fake_adapter(seen, "gemini-3.8-flash-high")}
    runs_dir = tmp_path / "runs"

    run_workflow(
        workflow=wf,
        runs_root=runs_dir,
        workdir=tmp_path,
        root=tmp_path,
        adapters=adapters,
        resolved=resolved,
    )

    assert len(seen) == 1
    # Prompt is verbatim unchanged
    assert seen[0]["prompt"] == p_content


# =====================================================================
# 4. Path Security Guard: Whitespace and Non-ASCII Characters
# =====================================================================


def test_path_with_whitespace_falls_back_to_none_and_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _setup_roles_and_models(tmp_path, monkeypatch)

    # Create home directory with space
    spaced_home = tmp_path / "user with space"
    agents_dir = spaced_home / ".agents" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    builder_md = agents_dir / "builder.md"
    builder_md.write_text(
        """---
name: builder
description: good builder
---
Principles.
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_USER_HOME", str(spaced_home))

    profile = MachineProfile(cli_dirs={"agents": str(spaced_home / ".agents")})
    save_machine_profile(profile, home=tmp_path / ".aiwork")

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    p_content = "Prompt for whitespace path test."
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text(p_content, encoding="utf-8")

    step = StepSpec(
        id="s_space",
        role="builder",
        prompt_file=str(prompt_file),
        test_command=PASS,
    )
    wf = WorkflowSpec(id="wf_space", brief_path=str(brief), steps=[step])

    with pytest.warns(UserWarning, match="whitespace"):
        resolved = resolve_workflow(wf, cli_checker=lambda _: True)

    expected_posix = builder_md.resolve().as_posix()
    assert resolved.steps["s_space"].role_file == expected_posix
    assert resolved.steps["s_space"].delivery == "none"

    seen: list[dict] = []
    adapters = {"gemini": _fake_adapter(seen, "gemini-3.8-flash-high")}
    runs_dir = tmp_path / "runs"

    run_workflow(
        workflow=wf,
        runs_root=runs_dir,
        workdir=tmp_path,
        root=tmp_path,
        adapters=adapters,
        resolved=resolved,
    )

    assert len(seen) == 1
    # Header is NOT added; prompt is verbatim
    assert seen[0]["prompt"] == p_content


def test_path_with_non_ascii_falls_back_to_none_and_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _setup_roles_and_models(tmp_path, monkeypatch)

    # Create home directory with non-ASCII Chinese characters
    unicode_home = tmp_path / "專案目錄"
    agents_dir = unicode_home / ".agents" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    builder_md = agents_dir / "builder.md"
    builder_md.write_text(
        """---
name: builder
description: good builder
---
Principles.
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_USER_HOME", str(unicode_home))

    profile = MachineProfile(cli_dirs={"agents": str(unicode_home / ".agents")})
    save_machine_profile(profile, home=tmp_path / ".aiwork")

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    p_content = "Prompt for unicode path test."
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text(p_content, encoding="utf-8")

    step = StepSpec(
        id="s_unicode",
        role="builder",
        prompt_file=str(prompt_file),
        test_command=PASS,
    )
    wf = WorkflowSpec(id="wf_unicode", brief_path=str(brief), steps=[step])

    with pytest.warns(UserWarning, match="invalid characters"):
        resolved = resolve_workflow(wf, cli_checker=lambda _: True)

    assert resolved.steps["s_unicode"].delivery == "none"

    seen: list[dict] = []
    adapters = {"gemini": _fake_adapter(seen, "gemini-3.8-flash-high")}
    runs_dir = tmp_path / "runs"

    run_workflow(
        workflow=wf,
        runs_root=runs_dir,
        workdir=tmp_path,
        root=tmp_path,
        adapters=adapters,
        resolved=resolved,
    )

    assert len(seen) == 1
    # Header is NOT added; prompt is verbatim
    assert seen[0]["prompt"] == p_content


# =====================================================================
# 5. resolved.json Storage, Loading, and Resume Continuity
# =====================================================================


def test_resolved_json_storage_and_roundtrip(tmp_path: Path):
    run_dir = tmp_path / "run_test"
    run_dir.mkdir(parents=True, exist_ok=True)

    wf_resolved = ResolvedWorkflow(
        version=1,
        resolved_at="2026-10-17T00:00:00Z",
        tables={
            "roles": TableMetadata(path="/test/roles.yaml", sha256="abc"),
            "models": TableMetadata(path="/test/models.yaml", sha256="def"),
        },
        steps={
            "s1": ResolvedStep(
                step_id="s1",
                role="builder",
                agent="gemini",
                model="gemini-3.8-flash-high",
                source="shared",
                role_file="C:/Users/<user>/.agents/agents/builder.md",
                delivery="prompt-path",
            ),
            "s2": ResolvedStep(
                step_id="s2",
                role="writer",
                agent="cursor",
                model="composer-2.5",
                source="shared",
                role_file="C:/bad path/writer.md",
                delivery="none",
            ),
            "s3": ResolvedStep(
                step_id="s3",
                role=None,
                agent="cursor",
                model="composer-2.5",
                source="explicit",
                role_file=None,
                delivery="none",
            ),
        },
    )

    saved_path = save_resolved(run_dir, wf_resolved)
    assert saved_path.is_file()

    loaded = load_resolved(run_dir)
    assert loaded.steps["s1"].role_file == "C:/Users/<user>/.agents/agents/builder.md"
    assert loaded.steps["s1"].delivery == "prompt-path"

    assert loaded.steps["s2"].role_file == "C:/bad path/writer.md"
    assert loaded.steps["s2"].delivery == "none"

    assert loaded.steps["s3"].role_file is None
    assert loaded.steps["s3"].delivery == "none"


def test_resume_uses_pinned_role_file_and_delivery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _setup_roles_and_models(tmp_path, monkeypatch)

    user_home = tmp_path / "fake_user_home"
    agents_dir = user_home / ".agents" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    builder_md = agents_dir / "builder.md"
    builder_md.write_text(
        """---
name: builder
description: good builder
---
Principles.
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_USER_HOME", str(user_home))

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    p1 = tmp_path / "p1.md"
    p1.write_text("Step 1 prompt", encoding="utf-8")
    p2 = tmp_path / "p2.md"
    p2.write_text("Step 2 prompt", encoding="utf-8")

    wf = WorkflowSpec(
        id="wf_resume_test",
        brief_path=str(brief),
        steps=[
            StepSpec(id="s1", role="builder", prompt_file=str(p1), test_command=PASS),
            StepSpec(id="s2", role="builder", approval=True, prompt_file=str(p2), test_command=PASS),
        ],
    )

    seen: list[dict] = []
    adapters = {"gemini": _fake_adapter(seen, "gemini-3.8-flash-high")}
    runs_dir = tmp_path / "runs"

    resolved = resolve_workflow(wf, cli_checker=lambda _: True)
    assert resolved.steps["s2"].delivery == "prompt-path"

    # Run step 1, pause before step 2 due to approval: true
    run_dir = run_workflow(
        workflow=wf,
        runs_root=runs_dir,
        workdir=tmp_path,
        root=tmp_path,
        adapters=adapters,
        resolved=resolved,
    )

    # Approve step 2
    (run_dir / "approvals" / "s2.approved").write_text("ok", encoding="utf-8")

    # Now simulate deleting the role definition file on disk!
    builder_md.unlink()
    assert not builder_md.exists()

    # Resume run: must still use the pinned role_file and delivery from resolved.json!
    run_workflow(
        workflow=wf,
        runs_root=runs_dir,
        workdir=tmp_path,
        root=tmp_path,
        adapters=adapters,
        resume_run_id=run_dir.name,
    )

    assert len(seen) == 2
    posix_path = builder_md.resolve().as_posix()
    # Step 2 received the injected header because it was pinned in resolved.json
    assert seen[1]["prompt"].startswith(f"@{posix_path}\n請依上面這個角色檔的工作原則執行下面的任務。\n\n")


def test_re_resolve_updates_incomplete_step_delivery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _setup_roles_and_models(tmp_path, monkeypatch)

    user_home = tmp_path / "fake_user_home"
    agents_dir = user_home / ".agents" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    builder_md = agents_dir / "builder.md"
    builder_md.write_text(
        """---
name: builder
description: good builder
---
Principles.
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_USER_HOME", str(user_home))

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    p1 = tmp_path / "p1.md"
    p1.write_text("Step 1 prompt", encoding="utf-8")
    p2 = tmp_path / "p2.md"
    p2.write_text("Step 2 prompt", encoding="utf-8")

    wf = WorkflowSpec(
        id="wf_reresolve_test",
        brief_path=str(brief),
        steps=[
            StepSpec(id="s1", role="builder", prompt_file=str(p1), test_command=PASS),
            StepSpec(id="s2", role="writer", approval=True, prompt_file=str(p2), test_command=PASS),
        ],
    )

    seen: list[dict] = []
    adapters = {"gemini": _fake_adapter(seen, "gemini-3.8-flash-high"), "cursor": _fake_adapter(seen, "composer-2.5")}
    runs_dir = tmp_path / "runs"

    resolved = resolve_workflow(wf, cli_checker=lambda _: True)
    # writer has no definition initially
    assert resolved.steps["s2"].delivery == "none"

    run_dir = run_workflow(
        workflow=wf,
        runs_root=runs_dir,
        workdir=tmp_path,
        root=tmp_path,
        adapters=adapters,
        resolved=resolved,
    )

    # Now create writer definition before re-resolving
    writer_md = agents_dir / "writer.md"
    writer_md.write_text(
        """---
name: writer
description: good writer
---
Writing principles.
""",
        encoding="utf-8",
    )

    # Re-resolve run
    updated_resolved = re_resolve_run(wf, run_dir, cli_checker=lambda _: True)
    # s1 completed -> retained
    assert updated_resolved.steps["s1"].role_file == builder_md.resolve().as_posix()
    assert updated_resolved.steps["s1"].delivery == "prompt-path"
    # s2 incomplete -> updated to writer.md with prompt-path
    assert updated_resolved.steps["s2"].role_file == writer_md.resolve().as_posix()
    assert updated_resolved.steps["s2"].delivery == "prompt-path"
