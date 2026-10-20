import json
import sqlite3
from pathlib import Path
import pytest
from typer.testing import CliRunner

from aiwork.adapters.base import AdapterResult
from aiwork.cli import app
from aiwork.dispatch import load_resolved
from aiwork.models import StepSpec, UsageEvent, WorkflowSpec
from aiwork.runner import run_workflow
from aiwork.usage_db import insert_event, list_events, usage_db_path
from aiwork.usage_view import _row

PASS = 'python -c "import sys; sys.exit(0)"'


def _fake_adapter(model_actual="test-model"):
    return lambda **kw: AdapterResult(
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


def test_sqlite_migration_and_dispatch_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "legacy.sqlite"
    monkeypatch.setenv("AIWORK_USAGE_DB", str(db_file))

    # Create a legacy table without dispatch_role column
    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE usage_event (
          id INTEGER PRIMARY KEY,
          recorded_at TEXT NOT NULL,
          repo_root TEXT NOT NULL,
          run_id TEXT NOT NULL,
          workflow_id TEXT NOT NULL,
          step_id TEXT NOT NULL,
          agent TEXT NOT NULL,
          model_requested TEXT NOT NULL,
          model_actual TEXT NOT NULL,
          effort TEXT NOT NULL,
          input_uncached INTEGER NOT NULL DEFAULT 0,
          cache_read INTEGER NOT NULL DEFAULT 0,
          cache_write INTEGER NOT NULL DEFAULT 0,
          output INTEGER NOT NULL DEFAULT 0,
          session_id TEXT,
          dirty INTEGER NOT NULL DEFAULT 0,
          mismatch INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL DEFAULT 'run'
        )
        """
    )
    conn.commit()
    conn.close()

    # Now use aiwork usage_db insert_event, which connects and auto-migrates
    event = UsageEvent(
        run_id="r1",
        step_id="s1",
        agent="gemini",
        dispatch_role="builder",
        model_requested="gemini-3.8-flash-high",
        model_actual="gemini-3.8-flash-high",
    )
    ok = insert_event(tmp_path, event, workflow_id="wf1")
    assert ok is True

    rows = list_events(tmp_path)
    assert len(rows) == 1
    assert rows[0]["dispatch_role"] == "builder"
    assert rows[0]["agent"] == "gemini"


def test_usage_view_row_contains_role():
    ev = {
        "run_id": "r1",
        "step_id": "s1",
        "agent": "gemini",
        "dispatch_role": "builder",
        "model_actual": "gemini-3.8-flash-high",
        "input_uncached": 100,
        "cache_read": 50,
        "cache_write": 0,
        "output": 30,
    }
    row = _row("r1", ev, None)
    assert row["role"] == "builder"
    assert row["agent"] == "gemini"
    assert row["model"] == "gemini-3.8-flash-high"


def _setup_config_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builder_model="gemini-3.8-flash-high"):
    (tmp_path / "mcp-profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "mcp-profiles" / "default.yaml").write_text("servers: []\n", encoding="utf-8")
    roles_file = tmp_path / "config" / "roles.yaml"
    roles_file.parent.mkdir(parents=True, exist_ok=True)
    roles_file.write_text(
        f"""
version: 1
roles:
  builder:
    agent: gemini
    model: {builder_model}
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
    - id: composer-2.5-fast
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))
    return roles_file, models_file


def test_cli_run_invalid_workflow_creates_no_runs_e3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _setup_config_files(tmp_path, monkeypatch)
    runner = CliRunner()

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    prompt = tmp_path / "p.md"
    prompt.write_text("p", encoding="utf-8")

    wf_file = tmp_path / "bad_wf.yaml"
    wf_file.write_text(
        f"""
id: bad_wf
brief_path: {brief.name}
steps:
  - id: s1
    role: nonexistent-role
    prompt_file: {prompt.name}
    test_command: '{PASS}'
""",
        encoding="utf-8",
    )

    runs_dir = tmp_path / "runs"
    res = runner.invoke(app, ["run", str(wf_file), "--runs-root", str(runs_dir), "--root", str(tmp_path)])
    assert res.exit_code == 1
    assert "nonexistent-role" in res.output or "nonexistent-role" in (res.stderr or "")
    # Must not have created runs directory or any run inside it
    if runs_dir.exists():
        assert len(list(runs_dir.iterdir())) == 0



def test_e4_change_table_updates_subsequent_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    roles_file, _ = _setup_config_files(tmp_path, monkeypatch, builder_model="gemini-3.8-flash-high")
    runner = CliRunner()

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    prompt1 = tmp_path / "p1.md"
    prompt1.write_text("p1", encoding="utf-8")
    prompt2 = tmp_path / "p2.md"
    prompt2.write_text("p2", encoding="utf-8")

    wf1 = tmp_path / "wf1.yaml"
    wf1.write_text(
        f"""
id: wf1
brief_path: {brief.name}
steps:
  - id: s1
    role: builder
    prompt_file: {prompt1.name}
    test_command: '{PASS}'
""",
        encoding="utf-8",
    )

    runs_dir = tmp_path / "runs"

    # First run uses initial builder model gemini-3.8-flash-high
    # Note: run_workflow in CLI creates adapters that run real CLI, so we can monkeypatch _build_adapters
    monkeypatch.setattr(
        "aiwork.cli._build_adapters",
        lambda root: {"gemini": _fake_adapter("gemini-3.8-flash-high"), "cursor": _fake_adapter("composer-2.5")},
    )

    res1 = runner.invoke(app, ["run", str(wf1), "--runs-root", str(runs_dir), "--root", str(tmp_path)])
    assert res1.exit_code == 0
    run1_dir = Path(res1.output.splitlines()[0].strip())
    resolved1 = load_resolved(run1_dir)
    assert resolved1.steps["s1"].model == "gemini-3.8-flash-high"

    # Now change roles table to gemini-3.8-flash-low
    roles_file.write_text(
        """
version: 1
roles:
  builder:
    agent: gemini
    model: gemini-3.8-flash-low
    description: updated builder
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "aiwork.cli._build_adapters",
        lambda root: {"gemini": _fake_adapter("gemini-3.8-flash-low")},
    )

    res2 = runner.invoke(app, ["run", str(wf1), "--runs-root", str(runs_dir), "--root", str(tmp_path)])
    assert res2.exit_code == 0
    run2_dir = Path(res2.output.splitlines()[0].strip())
    resolved2 = load_resolved(run2_dir)
    assert resolved2.steps["s1"].model == "gemini-3.8-flash-low"


def test_e5_resume_pins_and_re_resolve_updates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    roles_file, _ = _setup_config_files(tmp_path, monkeypatch)
    runner = CliRunner()

    brief = tmp_path / "brief.md"
    brief.write_text("b", encoding="utf-8")
    prompt1 = tmp_path / "p1.md"
    prompt1.write_text("p1", encoding="utf-8")
    prompt2 = tmp_path / "p2.md"
    prompt2.write_text("p2", encoding="utf-8")

    wf = tmp_path / "wf_pause.yaml"
    wf.write_text(
        f"""
id: wf_pause
brief_path: {brief.name}
steps:
  - id: s1
    role: builder
    prompt_file: {prompt1.name}
    test_command: '{PASS}'
  - id: s2
    role: writer
    approval: true
    prompt_file: {prompt2.name}
    test_command: '{PASS}'
""",
        encoding="utf-8",
    )

    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(
        "aiwork.cli._build_adapters",
        lambda root: {"gemini": _fake_adapter("gemini-3.8-flash-high"), "cursor": _fake_adapter("composer-2.5")},
    )

    # Start run: s1 runs, pauses before s2 due to approval: true
    res1 = runner.invoke(app, ["run", str(wf), "--runs-root", str(runs_dir), "--root", str(tmp_path)])
    run_dir = Path(res1.output.splitlines()[0].strip())
    resolved_init = load_resolved(run_dir)
    assert resolved_init.steps["s2"].model == "composer-2.5"

    # Status check
    res_status = runner.invoke(app, ["status", "--runs-root", str(runs_dir)])
    assert "role=writer->cursor/composer-2.5" in res_status.output

    # Approve s2
    runner.invoke(app, ["approve", run_dir.name, "s2", "--runs-root", str(runs_dir)])

    # Now change roles table: change writer model to composer-2.5-fast
    roles_file.write_text(
        """
version: 1
roles:
  builder:
    agent: gemini
    model: gemini-3.8-flash-high
    description: builder
  writer:
    agent: cursor
    model: composer-2.5-fast
    description: fast writer
""",
        encoding="utf-8",
    )

    # Resume WITHOUT --re-resolve: must keep pinned model composer-2.5!
    res_resume = runner.invoke(
        app,
        ["run", str(wf), "--resume", run_dir.name, "--runs-root", str(runs_dir), "--root", str(tmp_path)],
    )
    assert res_resume.exit_code == 0
    resolved_after_resume = load_resolved(run_dir)
    assert resolved_after_resume.steps["s2"].model == "composer-2.5"

    # Now test --re-resolve: reset s2 (simulate failure or restart of s2)
    (run_dir / "steps" / "s2" / "ok").unlink(missing_ok=True)
    res_reresolve = runner.invoke(
        app,
        ["run", str(wf), "--resume", run_dir.name, "--re-resolve", "--runs-root", str(runs_dir), "--root", str(tmp_path)],
    )
    assert res_reresolve.exit_code == 0
    resolved_reresolved = load_resolved(run_dir)
    # s2 is now updated to composer-2.5-fast
    assert resolved_reresolved.steps["s2"].model == "composer-2.5-fast"
    # s1 was already ok, so kept as gemini-3.8-flash-high
    assert resolved_reresolved.steps["s1"].model == "gemini-3.8-flash-high"
    # history has previous snapshot
    assert len(resolved_reresolved.history) >= 1
    assert resolved_reresolved.history[-1]["steps"]["s2"]["model"] == "composer-2.5"
