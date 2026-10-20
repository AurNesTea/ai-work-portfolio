import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "panel" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import snapshot_server  # noqa: E402

EVIL = "http://evil.example"
PANEL = "http://localhost:1420"


@pytest.fixture
def test_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "root"
    (root / "runs").mkdir(parents=True)
    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        """version: 1
roles:
  builder:
    agent: gemini
    model: gemini-3.8-flash-high
    effort: high
    description: good builder
""",
        encoding="utf-8",
    )
    models_file = tmp_path / "models.yaml"
    models_file.write_text(
        """version: 1
models:
  gemini:
    - id: gemini-3.8-flash-high
  cursor:
    - id: composer-2.5
  claude:
    - id: claude-opus-5-5
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))
    monkeypatch.setenv("AIWORK_HOME", str(tmp_path / "home"))

    srv = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        snapshot_server.make_handler(snapshot_server.ServerState(root)),
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port, root, roles_file, models_file
    srv.shutdown()
    srv.server_close()


def _req(port: int, path: str, method: str = "GET", headers: dict | None = None, body: bytes | None = None):
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


def test_e9_guard_and_body_limit(test_server):
    port, _, roles_file, models_file = test_server
    initial_roles_sha = snapshot_server.sha256_file(roles_file)
    initial_models_sha = snapshot_server.sha256_file(models_file)

    routes = [
        ("GET", "/roles", None),
        ("POST", "/roles", json.dumps({"target": "shared"}).encode()),
        ("GET", "/models", None),
        ("POST", "/models", json.dumps({}).encode()),
        ("POST", "/models/check", json.dumps({}).encode()),
    ]

    for method, path, b in routes:
        # 1. Evil origin -> 403
        status, _, _ = _req(port, path, method, {"Origin": EVIL, "Content-Type": "application/json"}, b)
        assert status == 403, f"{method} {path} should be 403 with evil origin"

        # 2. Evil host -> 403
        status, _, _ = _req(port, path, method, {"Host": f"rebind.example:{port}", "Content-Type": "application/json"}, b)
        assert status == 403, f"{method} {path} should be 403 with evil host"

    # Verify table hashes did not change
    assert snapshot_server.sha256_file(roles_file) == initial_roles_sha
    assert snapshot_server.sha256_file(models_file) == initial_models_sha

    # 3. Oversized body > 256 KB -> 413
    huge_body = b"x" * (257 * 1024)
    for path in ("/roles", "/models", "/models/check"):
        status, _, _ = _req(port, path, "POST", {"Origin": PANEL, "Content-Type": "application/json"}, huge_body)
        assert status == 413, f"POST {path} with >256KB body should return 413"


def test_roles_get_and_post_endpoints(test_server):
    port, _, roles_file, _ = test_server

    # GET /roles
    status, _, data = _req(port, "/roles", "GET", {"Origin": PANEL})
    assert status == 200
    res = json.loads(data)
    assert res["ok"] is True
    assert "builder" in res["roles"]
    assert "etags" in res
    shared_etag = res["etags"]["roles"]

    # POST /roles with wrong etag -> 409 conflict
    body_conflict = json.dumps({
        "target": "shared",
        "base_etag": "wrong_etag_123",
        "roles": {"builder": {"agent": "gemini", "model": "gemini-3.8-flash-high", "description": "desc"}}
    }).encode()
    status, _, _ = _req(port, "/roles", "POST", {"Origin": PANEL, "Content-Type": "application/json"}, body_conflict)
    assert status == 409

    # POST /roles with invalid model -> 400
    body_invalid = json.dumps({
        "target": "shared",
        "base_etag": shared_etag,
        "roles": {"builder": {"agent": "gemini", "model": "nonexistent-model", "description": "desc"}}
    }).encode()
    status, _, _ = _req(port, "/roles", "POST", {"Origin": PANEL, "Content-Type": "application/json"}, body_invalid)
    assert status == 400

    # POST /roles success
    body_ok = json.dumps({
        "target": "shared",
        "base_etag": shared_etag,
        "roles": {
            "builder": {"agent": "gemini", "model": "gemini-3.8-flash-high", "effort": "high", "description": "updated builder"},
            "writer": {"agent": "cursor", "model": "composer-2.5", "description": "new writer"}
        }
    }).encode()
    status, _, ok_data = _req(port, "/roles", "POST", {"Origin": PANEL, "Content-Type": "application/json"}, body_ok)
    assert status == 200
    ok_res = json.loads(ok_data)
    assert ok_res["ok"] is True
    assert "new_etag" in ok_res


def test_models_get_and_post_endpoints(test_server):
    port, _, _, models_file = test_server

    # GET /models
    status, _, data = _req(port, "/models", "GET", {"Origin": PANEL})
    assert status == 200
    res = json.loads(data)
    assert res["ok"] is True
    assert "gemini" in res["models"]
    model_etag = res["etag"]

    # POST /models conflict
    body_conflict = json.dumps({"base_etag": "bad_etag", "models": {}}).encode()
    status, _, _ = _req(port, "/models", "POST", {"Origin": PANEL, "Content-Type": "application/json"}, body_conflict)
    assert status == 409

    # POST /models ok
    body_ok = json.dumps({
        "base_etag": model_etag,
        "models": {
            "gemini": [{"id": "gemini-3.8-flash-high"}],
            "cursor": [{"id": "composer-2.5"}],
            "claude": [{"id": "claude-opus-5-5", "note": "未驗證"}]
        }
    }).encode()
    status, _, data = _req(port, "/models", "POST", {"Origin": PANEL, "Content-Type": "application/json"}, body_ok)
    assert status == 200
    res = json.loads(data)
    assert res["ok"] is True
    assert "new_etag" in res


def test_models_check_endpoint(test_server, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        snapshot_server,
        "check_models_catalog",
        lambda: {
            "cursor": {"status": "ok", "extra_in_cli": [], "missing_in_cli": [], "total_cli": 1, "total_catalog": 1},
            "gemini": {"status": "ok", "extra_in_cli": [], "missing_in_cli": [], "total_cli": 1, "total_catalog": 1},
            "claude": {"status": "notice", "message": "沒有列模型的指令", "total_catalog": 1},
        },
    )
    port, _, _, _ = test_server
    status, _, data = _req(port, "/models/check", "POST", {"Origin": PANEL, "Content-Type": "application/json"}, b"{}")
    assert status == 200
    res = json.loads(data)
    assert res["ok"] is True
    assert "result" in res
    assert "cursor" in res["result"]
