from pathlib import Path
import pytest
from typer.testing import CliRunner

from aiwork.adapters.base import AdapterResult
from aiwork.cli import app
from aiwork.dispatch import (
    load_models_catalog,
    load_resolved,
    load_roles,
    resolve_workflow,
)
from aiwork.resources import dispatch_rules_path
from aiwork.workflow import load_workflow


PASS = 'python -c "import sys; sys.exit(0)"'


def _fake_adapter(model_actual="test-model"):
    return lambda **kw: AdapterResult(
        exit_code=0,
        session_id=None,
        model_actual=model_actual,
        input_uncached=12,
        cache_read=8,
        cache_write=0,
        output=24,
        cost_usd=0.005,
        dirty=False,
        stdout="smoke-ok",
        stderr="",
    )


def test_e12_legacy_smoke_yaml_untouched_and_resolvable():
    """E12: workflows/smoke.yaml must remain untouched and directly loadable/resolvable."""
    repo_root = Path(__file__).resolve().parents[1]
    smoke_path = repo_root / "workflows" / "smoke.yaml"
    assert smoke_path.is_file()

    # Load workflow
    wf = load_workflow(smoke_path)
    assert wf.id == "smoke"
    assert len(wf.steps) == 2
    # Ensure neither step has role; both have agent and model
    for step in wf.steps:
        assert step.role is None
        assert step.agent == "cursor"
        assert step.model == "composer-2"

    # Resolving legacy workflow should keep explicit agent/model without error
    resolved = resolve_workflow(wf)
    assert resolved.steps["step1"].agent == "cursor"
    assert resolved.steps["step1"].model == "composer-2"
    assert resolved.steps["step1"].source == "explicit"
    assert resolved.steps["step2"].agent == "cursor"
    assert resolved.steps["step2"].model == "composer-2"
    assert resolved.steps["step2"].source == "explicit"


def test_e10_no_codex_in_dispatch_smoke_and_catalog():
    """E10: config files and dispatch smoke must not contain codex references."""
    repo_root = Path(__file__).resolve().parents[1]
    config_dir = repo_root / "config"
    for cfg in config_dir.glob("*.yaml"):
        text = cfg.read_text(encoding="utf-8").lower()
        assert "codex" not in text, f"Found codex in {cfg}"

    dispatch_smoke = repo_root / "workflows" / "dispatch-smoke.yaml"
    text = dispatch_smoke.read_text(encoding="utf-8").lower()
    assert "codex" not in text, f"Found codex in {dispatch_smoke}"


def test_e5_e6_dispatch_smoke_resolution_and_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """E5 and E6: Test dispatch-smoke workflow resolves builder/writer, runs, pauses, and records dispatch_role."""
    repo_root = Path(__file__).resolve().parents[1]
    dispatch_smoke_path = repo_root / "workflows" / "dispatch-smoke.yaml"
    assert dispatch_smoke_path.is_file()

    runner = CliRunner()
    runs_dir = tmp_path / "runs"

    monkeypatch.setattr(
        "aiwork.cli._build_adapters",
        lambda root: {
            "gemini": _fake_adapter("gemini-3.8-flash-high"),
            "cursor": _fake_adapter("composer-2.5"),
            "claude": _fake_adapter("claude-haiku-4-5"),
        },
    )

    # Run dispatch-smoke
    # Step 1 (builder) runs and succeeds; Step 2 (writer) has approval: true so it pauses
    res = runner.invoke(
        app,
        [
            "run",
            str(dispatch_smoke_path),
            "--runs-root",
            str(runs_dir),
            "--root",
            str(repo_root),
        ],
    )
    assert "awaiting_approval" in res.output
    run_dir = Path(res.output.splitlines()[0].strip())
    assert run_dir.is_dir()

    # Verify resolved.json was created
    resolved = load_resolved(run_dir)
    assert resolved.version == 1
    assert resolved.steps["step1"].role in ("builder", "frontend")
    assert resolved.steps["step1"].agent in ("gemini", "cursor")
    assert resolved.steps["step2"].role == "writer"
    assert resolved.steps["step2"].agent in ("cursor", "claude", "gemini")

    # Verify step1 completed and run is awaiting approval on step2
    status_doc = (run_dir / "status.json").read_text(encoding="utf-8")
    assert '"awaiting_approval"' in status_doc
    assert '"step2"' in status_doc

    # Approve step2
    res_approve = runner.invoke(app, ["approve", run_dir.name, "step2", "--runs-root", str(runs_dir)])
    assert res_approve.exit_code == 0

    # Resume to finish step2
    res_resume = runner.invoke(
        app,
        [
            "run",
            str(dispatch_smoke_path),
            "--resume",
            run_dir.name,
            "--runs-root",
            str(runs_dir),
            "--root",
            str(repo_root),
        ],
    )
    assert res_resume.exit_code == 0
    final_status = (run_dir / "status.json").read_text(encoding="utf-8")
    assert '"succeeded"' in final_status

    # Verify usage_events.jsonl records dispatch_role
    events_path = run_dir / "usage_events.jsonl"
    assert events_path.is_file()
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    import json
    ev1 = json.loads(lines[0])
    ev2 = json.loads(lines[1])
    assert ev1["dispatch_role"] in ("builder", "frontend")
    assert ev2["dispatch_role"] == "writer"


def test_e7_rules_path_accessible():
    """E7: aiwork rules-path returns existing valid file."""
    runner = CliRunner()
    res = runner.invoke(app, ["rules-path"])
    assert res.exit_code == 0
    p = Path(res.output.strip())
    assert p.is_file()
    assert p.resolve() == dispatch_rules_path().resolve()
    content = p.read_text(encoding="utf-8")
    assert "aiwork roles" in content
    assert "role:" in content
