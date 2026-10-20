"""P5.1 action helpers: path checks without spawning live agents."""
from pathlib import Path
import importlib.util


def _load():
    spec = importlib.util.spec_from_file_location(
        "actions",
        Path(__file__).resolve().parents[1] / "panel" / "scripts" / "actions.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_run_rejects_escape(tmp_path: Path):
    mod = _load()
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "ok.yaml").write_text("id: x\n", encoding="utf-8")
    assert mod.run_workflow(tmp_path, "../ok.yaml")["ok"] is False
    assert mod.run_workflow(tmp_path, "workflows/nope.yaml")["ok"] is False
    assert mod.list_workflows(tmp_path) == ["workflows/ok.yaml"]
    assert mod.approve_step(tmp_path, "a/b", "s1")["ok"] is False


def test_ids_cannot_climb_out_of_runs(tmp_path: Path, monkeypatch):
    mod = _load()
    spawned: list = []
    monkeypatch.setattr(mod, "_spawn_aiwork", lambda *a, **k: spawned.append(a) or {"ok": True})
    for bad in ("..", ".", "..\\x", "../x", "a/b", "a\\b", "", ".hidden", "x" * 200):
        assert mod.approve_step(tmp_path, "run1", bad)["ok"] is False, bad
        assert mod.approve_step(tmp_path, bad, "step1")["ok"] is False, bad
        if bad:  # an empty id means "the current run", which is allowed
            assert mod.cancel_run(tmp_path, bad)["ok"] is False, bad
        assert mod.continue_run(tmp_path, "workflows/ok.yaml", bad)["ok"] is False, bad
    assert spawned == []
    assert mod.approve_step(tmp_path, "8af1029f6dd6", "model-claude-installer")["ok"] is True
    assert mod.cancel_run(tmp_path, None)["ok"] is True


def test_fire_and_forget_run_does_not_hold_pipes(tmp_path: Path, monkeypatch):
    mod = _load()
    seen: dict = {}

    class FakeProc:
        pid = 7

    def fake_popen(cmd, **kwargs):
        seen.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
    assert mod._spawn_aiwork(tmp_path, ["run", "x"], timeout=None)["ok"] is True
    assert seen["stdout"] is mod.subprocess.DEVNULL
    assert seen["stderr"] is mod.subprocess.DEVNULL


def test_continue_survives_unreadable_status(tmp_path: Path):
    mod = _load()
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "ok.yaml").write_text("id: demo\n", encoding="utf-8")
    run = tmp_path / "runs" / "abc"
    run.mkdir(parents=True)
    (run / "status.json").write_text('{"state": "wait', encoding="utf-8")
    assert mod.continue_run(tmp_path, "workflows/ok.yaml", "abc")["ok"] is False


def test_continue_resumes_waiting_run_only(tmp_path: Path, monkeypatch):
    mod = _load()
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "ok.yaml").write_text("id: demo\n", encoding="utf-8")
    run = tmp_path / "runs" / "abc"
    run.mkdir(parents=True)
    (run / "status.json").write_text(
        '{"state":"waiting","workflow_id":"demo","run_id":"abc"}',
        encoding="utf-8",
    )
    spawned: dict = {}

    def fake_spawn(root, args, timeout=None):
        spawned["args"] = args
        return {"ok": True, "detail": "started pid=1"}

    monkeypatch.setattr(mod, "_spawn_aiwork", fake_spawn)
    assert mod.continue_run(tmp_path, "../ok.yaml", "abc")["ok"] is False
    assert mod.continue_run(tmp_path, "workflows/ok.yaml", "a/b")["ok"] is False
    assert spawned == {}
    (run / "status.json").write_text(
        '{"state":"failed","workflow_id":"demo","run_id":"abc"}',
        encoding="utf-8",
    )
    failed = mod.continue_run(tmp_path, "workflows/ok.yaml", "abc")
    assert failed["ok"] is False
    assert failed["detail"] == "沒有可繼續的執行"
    (run / "status.json").write_text(
        '{"state":"waiting","workflow_id":"other","run_id":"abc"}',
        encoding="utf-8",
    )
    mismatch = mod.continue_run(tmp_path, "workflows/ok.yaml", "abc")
    assert mismatch["ok"] is False
    (run / "status.json").write_text(
        '{"state":"waiting","workflow_id":"demo","run_id":"abc"}',
        encoding="utf-8",
    )
    ok = mod.continue_run(tmp_path, "workflows/ok.yaml", "abc")
    assert ok["ok"] is True
    assert spawned["args"][-2:] == ["--resume", "abc"]
