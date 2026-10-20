from __future__ import annotations

import io
import json
import os
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
import pytest
from typer.testing import CliRunner

SCRIPTS = Path(__file__).resolve().parents[1] / "panel" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import snapshot_server  # noqa: E402
from aiwork.adapters.base import AdapterResult
from aiwork.cli import app
from aiwork.packs import (
    load_manifest,
    load_probe_results,
    probe_single_agent,
    run_probe,
    save_machine_profile,
    MachineProfile,
)

EVIL = "http://evil.example"
PANEL = "http://localhost:1420"
runner = CliRunner()


@pytest.fixture
def test_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "root"
    (root / "runs").mkdir(parents=True)
    home_dir = tmp_path / "aiwork_home"
    user_home_dir = tmp_path / "user_home"
    home_dir.mkdir(parents=True)
    user_home_dir.mkdir(parents=True)

    lib_dir = home_dir / "library"
    lib_dir.mkdir(parents=True)

    monkeypatch.setenv("AIWORK_HOME", str(home_dir))
    monkeypatch.setenv("AIWORK_USER_HOME", str(user_home_dir))

    # Seed machine.yaml
    profile = MachineProfile(
        name="test-machine",
        scope="global",
        libraries=[str(lib_dir)],
        enabled_packs=[],
        cli_dirs={
            "agents": str(user_home_dir / ".agents"),
            "claude": str(user_home_dir / ".claude"),
            "cursor": str(user_home_dir / ".cursor"),
            "gemini": str(user_home_dir / ".gemini"),
        },
    )
    save_machine_profile(profile, home=home_dir)

    # Seed roles and models for probe lookups
    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        """version: 1
roles:
  builder:
    agent: cursor
    model: composer-2.5
    description: builder role
""",
        encoding="utf-8",
    )
    models_file = tmp_path / "models.yaml"
    models_file.write_text(
        """version: 1
models:
  cursor:
    - id: composer-2.5
  gemini:
    - id: gemini-3.8-flash-high
  claude:
    - id: claude-opus-5-5
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))

    srv = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        snapshot_server.make_handler(snapshot_server.ServerState(root)),
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port, root, home_dir, user_home_dir
    srv.shutdown()
    srv.server_close()


def _req(
    port: int,
    path: str,
    method: str = "GET",
    headers: dict | None = None,
    body: bytes | None = None,
):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
    except (ConnectionAbortedError, ConnectionResetError):
        return 403, {}, b""


# =====================================================================
# 1. Probe Unit & Discrimination Tests (F11)
# =====================================================================


def test_probe_single_agent_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AIWORK_HOME", str(tmp_path))
    monkeypatch.setattr("aiwork.packs.check_cli_status", lambda ag: "ok")

    captured_prompts = []

    def mock_adapter(**kw):
        captured_prompts.append(kw["prompt"])
        import re

        secret = "NONE"
        lines = kw["prompt"].splitlines()
        if lines and lines[0].startswith("@"):
            role_p = Path(lines[0][1:].strip())
            if role_p.is_file():
                content = role_p.read_text(encoding="utf-8")
                m = re.search(r"\[probe-[a-f0-9-]+\]", content)
                if m:
                    secret = m.group(0)

        return AdapterResult(
            exit_code=0,
            session_id="s1",
            model_actual="test-model",
            input_uncached=10,
            cache_read=0,
            cache_write=0,
            output=10,
            cost_usd=None,
            dirty=False,
            stdout=f"Hello! My reply includes {secret}.",
            stderr="",
            final_text=f"Done {secret}",
        )

    res = probe_single_agent("cursor", home=tmp_path, adapter_fn=mock_adapter)
    assert res["passed"] is True
    assert res["status"] == "passed"
    assert res["label"] == "通過"
    assert len(captured_prompts) == 1
    assert "@" in captured_prompts[0]


def test_probe_single_agent_failure_secret_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("AIWORK_HOME", str(tmp_path))
    monkeypatch.setattr("aiwork.packs.check_cli_status", lambda ag: "ok")

    def mock_adapter(**kw):
        return AdapterResult(
            exit_code=0,
            session_id="s1",
            model_actual="test-model",
            input_uncached=10,
            cache_read=0,
            cache_write=0,
            output=10,
            cost_usd=None,
            dirty=False,
            stdout="Hello! I did not output the secret.",
            stderr="",
            final_text="Just normal answer",
        )

    res = probe_single_agent("cursor", home=tmp_path, adapter_fn=mock_adapter)
    assert res["passed"] is False
    assert res["status"] == "failed"
    assert res["label"] == "未通過"


def test_f11_probe_discrimination_nonexistent_role_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """F11: If probe role file path is nonexistent, delivery fallback does not inject secret,
    so agent does not output it and probe reports '未通過', not false pass."""
    monkeypatch.setenv("AIWORK_HOME", str(tmp_path))
    monkeypatch.setattr("aiwork.packs.check_cli_status", lambda ag: "ok")

    def mock_adapter(**kw):
        # The agent answers normally without the secret because prompt has no role header
        return AdapterResult(
            exit_code=0,
            session_id="s1",
            model_actual="test-model",
            input_uncached=10,
            cache_read=0,
            cache_write=0,
            output=10,
            cost_usd=None,
            dirty=False,
            stdout="Normal reply without secret.",
            stderr="",
            final_text="Normal reply.",
        )

    nonexistent_path = tmp_path / "does_not_exist_role.md"
    res = probe_single_agent(
        "cursor",
        home=tmp_path,
        role_file_override=nonexistent_path,
        adapter_fn=mock_adapter,
    )
    assert res["passed"] is False
    assert res["status"] == "failed"
    assert res["label"] == "未通過"


def test_probe_missing_and_logged_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AIWORK_HOME", str(tmp_path))

    monkeypatch.setattr("aiwork.packs.check_cli_status", lambda ag: "missing")
    res_missing = probe_single_agent("gemini", home=tmp_path)
    assert res_missing["passed"] is False
    assert res_missing["status"] == "missing"
    assert res_missing["label"] == "沒裝"

    monkeypatch.setattr("aiwork.packs.check_cli_status", lambda ag: "not_logged_in")
    res_logged_out = probe_single_agent("claude", home=tmp_path)
    assert res_logged_out["passed"] is False
    assert res_logged_out["status"] == "not_logged_in"
    assert res_logged_out["label"] == "未登入"


def test_probe_cli_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AIWORK_HOME", str(tmp_path))
    monkeypatch.setattr("aiwork.packs.check_cli_status", lambda ag: "ok")

    def mock_adapter(**kw):
        import re

        secret = "NONE"
        lines = kw["prompt"].splitlines()
        if lines and lines[0].startswith("@"):
            role_p = Path(lines[0][1:].strip())
            if role_p.is_file():
                content = role_p.read_text(encoding="utf-8")
                m = re.search(r"\[probe-[a-f0-9-]+\]", content)
                if m:
                    secret = m.group(0)

        return AdapterResult(
            exit_code=0,
            session_id=None,
            model_actual="test",
            input_uncached=0,
            cache_read=0,
            cache_write=0,
            output=0,
            cost_usd=0,
            dirty=False,
            stdout=secret,
            stderr="",
            final_text=secret,
        )

    # Test run_probe directly
    probe_res = run_probe(home=tmp_path, adapter_fn=mock_adapter)
    assert "updated_at" in probe_res
    assert probe_res["cursor"]["passed"] is True

    # Test CLI output
    monkeypatch.setattr("aiwork.packs.run_probe", lambda agent=None, **kw: {
        "updated_at": "2026-10-19T00:00:00Z",
        "results": {
            "cursor": {
                "status": "passed",
                "label": "通過",
                "passed": True,
                "model": "composer-2.5",
                "detail": "",
            }
        },
        "cursor": {
            "status": "passed",
            "label": "通過",
            "passed": True,
            "model": "composer-2.5",
            "detail": "",
        },
    })

    result = runner.invoke(app, ["packs", "probe", "--agent", "cursor"])
    assert result.exit_code == 0
    assert "cursor" in result.output
    assert "通過" in result.output

    # JSON output
    result_json = runner.invoke(app, ["packs", "probe", "--agent", "cursor", "--json"])
    assert result_json.exit_code == 0
    data = json.loads(result_json.output)
    assert data["cursor"]["passed"] is True


# =====================================================================
# 2. Server Guard and Body Limit Tests (F10)
# =====================================================================


def test_f10_new_endpoints_guard_403(test_server):
    port, _, _, _ = test_server

    endpoints = [
        ("GET", "/library", None),
        ("POST", "/library/upload", b"test"),
        ("POST", "/library/commit", json.dumps({"upload_id": "u", "pack_id": "p"}).encode()),
        ("POST", "/role", json.dumps({"id": "r"}).encode()),
        ("GET", "/machine", None),
        ("POST", "/machine/enable", json.dumps({"pack_id": "p"}).encode()),
        ("POST", "/machine/apply", json.dumps({"dry_run": True}).encode()),
        ("POST", "/machine/undo", json.dumps({}).encode()),
        ("POST", "/machine/probe", json.dumps({}).encode()),
    ]

    for method, path, b in endpoints:
        # Evil Origin
        status, _, _ = _req(
            port, path, method, {"Origin": EVIL, "Content-Type": "application/json"}, b
        )
        assert status == 403, f"{method} {path} should be 403 on evil Origin"

        # Evil Host
        status, _, _ = _req(
            port,
            path,
            method,
            {"Host": f"rebind.example:{port}", "Content-Type": "application/json"},
            b,
        )
        assert status == 403, f"{method} {path} should be 403 on bad Host"


def test_f10_oversized_request_body_413(test_server):
    port, _, _, _ = test_server

    # 1. /library/upload limit is 5 MB -> 5MB + 10KB should return 413
    huge_upload = b"x" * (5 * 1024 * 1024 + 10240)
    status, _, _ = _req(
        port,
        "/library/upload",
        "POST",
        {"Origin": PANEL, "Content-Type": "application/octet-stream"},
        huge_upload,
    )
    assert status == 413, "POST /library/upload > 5MB must return 413"

    # 2. Other POST endpoints limit is 256 KB -> 257 KB should return 413
    huge_post = b"x" * (257 * 1024)
    for path in (
        "/library/commit",
        "/role",
        "/machine/enable",
        "/machine/apply",
        "/machine/undo",
        "/machine/probe",
    ):
        status, _, _ = _req(
            port,
            path,
            "POST",
            {"Origin": PANEL, "Content-Type": "application/json"},
            huge_post,
        )
        assert status == 413, f"POST {path} > 256KB must return 413"


# =====================================================================
# 3. Full API Lifecycle: upload -> commit -> apply -> undo
# =====================================================================


def _make_test_pack_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "pack.yaml",
            """id: e2e-pack
name: e2e-pack
description: Pack for API lifecycle testing
version: 1
""",
        )
        zf.writestr(
            "agents/tester.md",
            """---
name: tester
description: Test agent role
---
# Instructions
Do tests properly.
""",
        )
        zf.writestr(
            "rules/test-rule.mdc",
            """---
description: Always write tests
---
# Test Rule
Rules are mandatory.
""",
        )
        zf.writestr(
            "skills/test-skill/SKILL.md",
            """---
name: test-skill
description: Useful testing skill
---
# Skill
Skill body.
""",
        )
    return buf.getvalue()


def test_full_api_lifecycle(test_server, monkeypatch: pytest.MonkeyPatch):
    port, _, home_dir, user_home_dir = test_server
    zip_bytes = _make_test_pack_zip()

    # 1. POST /library/upload
    status, _, data = _req(
        port,
        "/library/upload",
        "POST",
        {"Origin": PANEL, "Content-Type": "application/zip"},
        zip_bytes,
    )
    assert status == 200
    upload_res = json.loads(data)
    assert upload_res["ok"] is True
    upload_id = upload_res["upload_id"]
    assert upload_id
    assert len(upload_res["files"]) == 4

    # 2. POST /library/commit
    commit_payload = json.dumps({"upload_id": upload_id, "pack_id": "e2e-pack"}).encode()
    status, _, data = _req(
        port,
        "/library/commit",
        "POST",
        {"Origin": PANEL, "Content-Type": "application/json"},
        commit_payload,
    )
    assert status == 200
    commit_res = json.loads(data)
    assert commit_res["ok"] is True
    assert commit_res["pack_id"] == "e2e-pack"

    # 3. GET /library: Verify pack is now in library
    status, _, data = _req(port, "/library", "GET", {"Origin": PANEL})
    assert status == 200
    lib_res = json.loads(data)
    assert lib_res["ok"] is True
    pack_ids = [p["id"] for p in lib_res["packs"]]
    assert "e2e-pack" in pack_ids

    # 4. POST /machine/enable
    enable_payload = json.dumps({"pack_id": "e2e-pack", "enabled": True}).encode()
    status, _, data = _req(
        port,
        "/machine/enable",
        "POST",
        {"Origin": PANEL, "Content-Type": "application/json"},
        enable_payload,
    )
    assert status == 200
    en_res = json.loads(data)
    assert en_res["ok"] is True
    assert "e2e-pack" in en_res["enabled_packs"]

    # 5. POST /machine/apply (dry-run)
    dry_apply_payload = json.dumps({"dry_run": True}).encode()
    status, _, data = _req(
        port,
        "/machine/apply",
        "POST",
        {"Origin": PANEL, "Content-Type": "application/json"},
        dry_apply_payload,
    )
    assert status == 200
    dry_res = json.loads(data)
    assert dry_res["ok"] is True
    assert dry_res["dry_run"] is True
    assert len(dry_res["plans"]["add"]) > 0

    # 6. POST /machine/apply (real apply)
    real_apply_payload = json.dumps({"dry_run": False}).encode()
    status, _, data = _req(
        port,
        "/machine/apply",
        "POST",
        {"Origin": PANEL, "Content-Type": "application/json"},
        real_apply_payload,
    )
    assert status == 200
    apply_res = json.loads(data)
    assert apply_res["ok"] is True
    assert apply_res["applied_count"] > 0

    # Verify files created
    agents_dir = user_home_dir / ".agents" / "agents"
    assert (agents_dir / "tester.md").is_file()

    # 7. GET /machine: verify manifest has intact entries
    status, _, data = _req(port, "/machine", "GET", {"Origin": PANEL})
    assert status == 200
    mach_res = json.loads(data)
    assert mach_res["ok"] is True
    mach = mach_res["machine"]
    assert mach["applied_count"] > 0
    assert any(e["status"] == "intact" for e in mach["entries"])

    # 8. POST /machine/undo
    undo_payload = json.dumps({"packs": ["e2e-pack"]}).encode()
    status, _, data = _req(
        port,
        "/machine/undo",
        "POST",
        {"Origin": PANEL, "Content-Type": "application/json"},
        undo_payload,
    )
    assert status == 200
    undo_res = json.loads(data)
    assert undo_res["ok"] is True
    assert len(undo_res["removed"]) > 0
    assert not (agents_dir / "tester.md").exists()

    # 9. GET /machine: verify manifest entries removed
    status, _, data = _req(port, "/machine", "GET", {"Origin": PANEL})
    assert status == 200
    mach_res_after = json.loads(data)
    assert mach_res_after["machine"]["applied_count"] == 0


# =====================================================================
# 4. Role and Probe Endpoints Tests
# =====================================================================


def test_role_post_and_external_guard(test_server, monkeypatch: pytest.MonkeyPatch):
    port, _, home_dir, user_home_dir = test_server

    # 1. POST /role successfully creates local role
    role_payload = json.dumps({
        "id": "my-worker",
        "description": "My special worker",
        "principles": "# Principles\nAlways be helpful.",
        "skills": ["tdd"],
    }).encode()
    status, _, data = _req(
        port,
        "/role",
        "POST",
        {"Origin": PANEL, "Content-Type": "application/json"},
        role_payload,
    )
    assert status == 200
    res = json.loads(data)
    assert res["ok"] is True
    assert res["id"] == "my-worker"

    local_role_file = home_dir / "library" / "local-roles" / "agents" / "my-worker.md"
    assert local_role_file.is_file()

    # 2. Simulate externally managed role in ~/.agents/agents/external.md (not in manifest)
    ext_dir = user_home_dir / ".agents" / "agents"
    ext_dir.mkdir(parents=True, exist_ok=True)
    ext_file = ext_dir / "planner.md"
    ext_file.write_text("---\nname: planner\ndescription: kit planner\n---\n", encoding="utf-8")

    # Attempting to edit externally managed role returns 403
    ext_payload = json.dumps({
        "id": "planner",
        "description": "attempt modify kit planner",
        "principles": "bad override",
    }).encode()
    status, _, data = _req(
        port,
        "/role",
        "POST",
        {"Origin": PANEL, "Content-Type": "application/json"},
        ext_payload,
    )
    assert status == 403
    err_res = json.loads(data)
    assert "externally managed" in err_res["detail"]


def test_machine_probe_endpoint(test_server, monkeypatch: pytest.MonkeyPatch):
    port, _, _, _ = test_server
    monkeypatch.setattr(
        snapshot_server,
        "run_probe",
        lambda agent=None, **kw: {
            "updated_at": "2026-10-19T00:00:00Z",
            "results": {
                "cursor": {
                    "status": "passed",
                    "label": "通過",
                    "passed": True,
                    "model": "composer-2.5",
                }
            },
        },
    )

    probe_payload = json.dumps({"agent": "cursor"}).encode()
    status, _, data = _req(
        port,
        "/machine/probe",
        "POST",
        {"Origin": PANEL, "Content-Type": "application/json"},
        probe_payload,
    )
    assert status == 200
    res = json.loads(data)
    assert res["ok"] is True
    assert "results" in res
