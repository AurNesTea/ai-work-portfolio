import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


def _load_agents_mod():
    spec = importlib.util.spec_from_file_location(
        "agents",
        Path(__file__).resolve().parents[1] / "panel" / "scripts" / "agents.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_parse_claude_account_mappings():
    mod = _load_agents_mod()
    # team / pro / max
    assert mod.parse_claude_account({"loggedIn": True, "subscriptionType": "team", "orgName": "MockOrg"}) == "Team · MockOrg"
    assert mod.parse_claude_account({"loggedIn": True, "subscriptionType": "TEAM", "orgName": "MockOrg"}) == "Team · MockOrg"
    assert mod.parse_claude_account({"loggedIn": True, "subscriptionType": "pro", "orgName": "MockOrg"}) == "Pro · MockOrg"
    assert mod.parse_claude_account({"loggedIn": True, "subscriptionType": "max"}) == "Max"
    # Unknown subscriptionType passes as-is
    assert mod.parse_claude_account({"loggedIn": True, "subscriptionType": "enterprise", "orgName": "OrgX"}) == "enterprise · OrgX"
    # Missing orgName or empty orgName
    assert mod.parse_claude_account({"loggedIn": True, "subscriptionType": "team"}) == "Team"
    assert mod.parse_claude_account({"loggedIn": True, "subscriptionType": "team", "orgName": ""}) == "Team"
    assert mod.parse_claude_account({"loggedIn": True, "subscriptionType": "team", "orgName": "   "}) == "Team"
    assert mod.parse_claude_account({"loggedIn": True, "subscriptionType": "team", "orgName": None}) == "Team"


def test_parse_claude_account_invalid():
    mod = _load_agents_mod()
    # loggedIn false
    assert mod.parse_claude_account({"loggedIn": False, "subscriptionType": "team", "orgName": "MockOrg"}) is None
    # missing subscriptionType
    assert mod.parse_claude_account({"loggedIn": True, "orgName": "MockOrg"}) is None
    assert mod.parse_claude_account({"loggedIn": True, "subscriptionType": ""}) is None
    # non-dict
    assert mod.parse_claude_account(None) is None
    assert mod.parse_claude_account({}) is None
    assert mod.parse_claude_account("string") is None


def test_parse_cursor_account():
    mod = _load_agents_mod()
    # Normal
    assert mod.parse_cursor_account("✓ Logged in as mock_dev@example.com") == "mock_dev@example.com"
    # ANSI escape characters
    ansi_text = "\x1b[32m✓\x1b[0m Logged in as mock_dev@example.com\r\n"
    assert mod.parse_cursor_account(ansi_text) == "mock_dev@example.com"
    # Without checkmark
    assert mod.parse_cursor_account("Logged in as user123@test.local") == "user123@test.local"
    # Not logged in
    assert mod.parse_cursor_account("Not logged in") is None
    assert mod.parse_cursor_account("You are logged out") is None
    # Invalid
    assert mod.parse_cursor_account("") is None
    assert mod.parse_cursor_account(None) is None
    assert mod.parse_cursor_account("Some random status text") is None


def test_agent_rows_privacy_and_account_labels(monkeypatch, capsys, caplog, tmp_path):
    mod = _load_agents_mod()

    # Mock all binaries to be present in PATH
    monkeypatch.setattr(mod.shutil, "which", lambda cmd: f"/fake/bin/{cmd}")

    def fake_run(argv):
        cmd = argv[0]
        if cmd == "claude":
            # Claude output with sensitive internal fields
            data = {
                "loggedIn": True,
                "authMethod": "oauth",
                "apiProvider": "firstParty",
                "analyticsDisabled": True,
                "projectsDirectory": "/secret/path/projects",
                "configDirectory": "/secret/path/config",
                "email": "claude_user@example.test",
                "orgId": "org-secret-999",
                "orgName": "Acme Corp",
                "subscriptionType": "team",
            }
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(data), stderr="")
        elif cmd == "agent":
            return subprocess.CompletedProcess(argv, 0, stdout="\x1b[32m✓\x1b[0m Logged in as cursor_dev@example.test\n", stderr="")
        elif cmd == "codex":
            return subprocess.CompletedProcess(argv, 0, stdout="Logged in using ChatGPT\n", stderr="")
        elif cmd == "agy":
            return subprocess.CompletedProcess(argv, 0, stdout="ready\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(mod, "_run", fake_run)

    # Record directory state before
    before_files = list(tmp_path.rglob("*"))

    rows = mod.agent_rows()

    # Record directory state after
    after_files = list(tmp_path.rglob("*"))
    assert before_files == after_files, "agent_rows wrote files to disk!"

    # Verify no prints or logs
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert not any("cursor_dev@example.test" in rec.getMessage() for rec in caplog.records)
    assert not any("claude_user@example.test" in rec.getMessage() for rec in caplog.records)

    by_id = {r["id"]: r for r in rows}

    # Claude row check
    claude = by_id["claude"]
    assert claude["state"] == "logged_in"
    assert claude["account_label"] == "Team · Acme Corp"
    # Ensure sensitive fields are NEVER leaked
    for forbidden in ("orgId", "configDirectory", "projectsDirectory", "email", "authMethod"):
        assert forbidden not in claude
    assert "data" not in claude

    # Cursor row check
    cursor = by_id["cursor"]
    assert cursor["state"] == "logged_in"
    assert cursor["account_label"] == "cursor_dev@example.test"

    # Gemini and Codex row check: Must NOT have account_label
    gemini = by_id["gemini"]
    assert "account_label" not in gemini

    codex = by_id["codex"]
    assert "account_label" not in codex


def test_agent_rows_tolerates_errors(monkeypatch):
    mod = _load_agents_mod()
    monkeypatch.setattr(mod.shutil, "which", lambda cmd: f"/fake/bin/{cmd}")

    # Test error cases: non-JSON claude, timeout, loggedIn false
    def fake_run_error(argv):
        cmd = argv[0]
        if cmd == "claude":
            return subprocess.CompletedProcess(argv, 0, stdout="Not valid json output", stderr="warning")
        elif cmd == "agent":
            return subprocess.CompletedProcess(argv, 0, stdout="Not logged in\n", stderr="")
        elif cmd == "codex":
            raise subprocess.TimeoutExpired(argv, 20)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(mod, "_run", fake_run_error)

    rows = mod.agent_rows()
    by_id = {r["id"]: r for r in rows}

    assert by_id["claude"]["state"] == "logged_in"
    assert "account_label" not in by_id["claude"]

    assert by_id["cursor"]["state"] == "logged_out"
    assert "account_label" not in by_id["cursor"]

    assert by_id["codex"]["state"] == "unknown"
    assert "account_label" not in by_id["codex"]
