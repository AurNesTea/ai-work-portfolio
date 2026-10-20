import importlib.util
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "agents",
        Path(__file__).resolve().parents[1] / "panel" / "scripts" / "agents.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_login_commands_skip_api_billing():
    mod = _load()
    assert mod.LOGIN_ARGV["claude"] == ["claude", "auth", "login"]
    assert mod.LOGIN_ARGV["codex"] == ["codex", "login"]
    assert mod.LOGIN_ARGV["gemini"] == ["agy"]
    for argv in mod.LOGIN_ARGV.values():
        assert "--console" not in argv
        assert "--with-api-key" not in argv
    assert mod.start_agent_login("other")["ok"] is False


def test_logged_out_output_is_not_mistaken_for_logged_in():
    mod = _load()
    assert mod._logged_in("cursor", 0, "Not logged in") is False
    assert mod._logged_in("codex", 0, "You are logged out") is False
    assert mod._logged_in("cursor", 0, "✓ Logged in as me@example.com") is True
    assert mod._logged_in("codex", 0, "Logged in using ChatGPT") is True
    assert mod._logged_in("codex", 1, "Logged in using ChatGPT") is False
    assert mod._logged_in("claude", 0, '{"loggedIn": true}') is True
    assert mod._logged_in("claude", 0, '{\n  "loggedIn": false\n}') is False
    assert mod._logged_in("claude", 1, "") is False


def test_login_console_command_uses_the_cli(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod.os, "name", "nt")
    cmd = mod.login_console_command("cursor")
    assert cmd[:4] == ["cmd", "/c", "start", "Cursor"]
    assert cmd[-2:] == ["agent", "login"]


def test_logout_commands_and_execution(monkeypatch):
    mod = _load()
    assert mod.LOGOUT_ARGV["cursor"] == ["agent", "logout"]
    assert mod.LOGOUT_ARGV["claude"] == ["claude", "auth", "logout"]
    assert mod.LOGOUT_ARGV["codex"] == ["codex", "logout"]

    # Unknown agent
    assert mod.start_agent_logout("nonexistent")["ok"] is False

    # Gemini toggles logged out state
    mod._set_agent_logged_out("gemini", False)
    assert mod._is_agent_logged_out("gemini") is False
    res_out = mod.start_agent_logout("gemini")
    assert res_out["ok"] is True
    assert mod._is_agent_logged_out("gemini") is True

    res_in = mod.start_agent_login("gemini")
    assert res_in["ok"] is True
    assert mod._is_agent_logged_out("gemini") is False

    # Cursor logout with mocked _run
    import subprocess
    monkeypatch.setattr(mod.shutil, "which", lambda cmd: f"/fake/{cmd}")
    called = []
    def fake_run(argv):
        called.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="Logged out successfully", stderr="")
    monkeypatch.setattr(mod, "_run", fake_run)

    res_cursor = mod.start_agent_logout("cursor")
    assert res_cursor["ok"] is True
    assert called == [["agent", "logout"]]
