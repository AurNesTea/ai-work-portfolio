"""Panel server: cross-site refusal, unknown-agent refusal, PTY close, tolerant snapshot reads."""
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

import http_guard  # noqa: E402
import pty_manager  # noqa: E402
import snapshot_server  # noqa: E402

EVIL = "http://evil.example"
PANEL = "http://localhost:1420"


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "root"
    (root / "runs").mkdir(parents=True)
    srv = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        snapshot_server.make_handler(snapshot_server.ServerState(root)),
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port, root
    srv.shutdown()
    srv.server_close()


def _http(port, path, method="GET", headers=None, body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _shell():
    return ["cmd.exe"] if os.name == "nt" else ["/bin/sh"]


def _exits_at_once():
    return ["cmd.exe", "/c", "echo", "done"] if os.name == "nt" else ["/bin/sh", "-c", "echo done"]


def test_guard_origin_and_host(monkeypatch):
    for ok in (None, PANEL, "http://127.0.0.1:1420", "tauri://localhost", "http://tauri.localhost/"):
        assert http_guard.origin_allowed(ok), ok
    for bad in (EVIL, "null", "", "http://localhost:3000", "http://localhost:1420.evil.example"):
        assert not http_guard.origin_allowed(bad), bad
    for ok in (None, "127.0.0.1:8765", "localhost:8765", "[::1]:8765"):
        assert http_guard.host_allowed(ok), ok
    for bad in ("rebind.example:8765", "127.0.0.1.evil.example", "evil.example"):
        assert not http_guard.host_allowed(bad), bad
    monkeypatch.setenv("AIWORK_PANEL_ORIGINS", "http://localhost:3000, http://localhost:3001/")
    assert http_guard.origin_allowed("http://localhost:3000")
    assert http_guard.origin_allowed("http://localhost:3001")


def test_cross_origin_http_is_refused(server):
    port, root = server
    for method, path in (("GET", "/snapshot"), ("GET", "/agents"), ("OPTIONS", "/approve")):
        status, headers, _ = _http(port, path, method, {"Origin": EVIL})
        assert status == 403, (method, path)
        assert "Access-Control-Allow-Origin" not in headers
    status, _, _ = _http(port, "/snapshot", headers={"Host": f"rebind.example:{port}"})
    assert status == 403

    sentinel = root.parent / "pwned.approved"
    body = json.dumps({"run_id": "r1", "step_id": "..\\..\\..\\pwned"}).encode()
    status, _, _ = _http(
        port, "/approve", "POST", {"Origin": EVIL, "Content-Type": "application/json"}, body
    )
    assert status == 403
    assert not sentinel.exists()


def test_panel_origin_gets_its_own_origin_back_not_a_wildcard(server):
    port, _ = server
    status, headers, _ = _http(port, "/snapshot", headers={"Origin": PANEL})
    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == PANEL
    assert "Origin" in headers["Vary"]
    status, headers, _ = _http(port, "/snapshot")
    assert status == 200
    assert "Access-Control-Allow-Origin" not in headers


def test_snapshot_failure_is_a_500_not_a_dropped_connection(server, monkeypatch):
    port, _ = server

    def boom(root, selected):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(snapshot_server, "snapshot_plus", boom)
    status, _, body = _http(port, "/snapshot")
    assert status == 500
    assert json.loads(body)["ok"] is False


def test_snapshot_survives_torn_and_old_run_files(tmp_path):
    runs = tmp_path / "runs"
    (runs / "torn").mkdir(parents=True)
    (runs / "torn" / "status.json").write_text('{"run_id": "torn", "sta', encoding="utf-8")
    (runs / "old").mkdir()
    (runs / "old" / "status.json").write_text('{"run_id": "old"}', encoding="utf-8")
    (runs / "good").mkdir()
    (runs / "good" / "status.json").write_text(
        json.dumps(
            {"run_id": "good", "state": "succeeded", "workflow_id": "w", "updated_at": "2026-10-15T00:00:00+00:00"}
        ),
        encoding="utf-8",
    )
    event = {"model_actual": "m", "input_uncached": 3, "output": 4}
    (runs / "good" / "usage_events.jsonl").write_text(
        json.dumps(event) + '\n{"model_actual": "m", "inp', encoding="utf-8"
    )
    (runs / "current.json").write_text("{", encoding="utf-8")

    snap = snapshot_server.build_snapshot(tmp_path, None)

    assert [h["run_id"] for h in snap["history"]] == ["good"]
    assert snap["selected_run_id"] == "good"
    assert snap["usage_by_model"]["m"]["events"] == 1
    assert snap["current_run_id"] is None


def test_websocket_from_foreign_origin_is_refused(server, tmp_path, monkeypatch):
    from websockets.exceptions import InvalidStatus
    from websockets.sync.client import connect

    port, _ = server
    monkeypatch.setitem(pty_manager.INTERACTIVE_COMMANDS, "gemini", _shell())
    url = f"ws://127.0.0.1:{port}/pty?agent=gemini&cwd={tmp_path}"
    with pytest.raises(InvalidStatus) as exc:
        connect(url, origin=EVIL)
    assert exc.value.response.status_code == 403


def test_websocket_with_unknown_agent_is_refused_not_given_a_shell(server, tmp_path):
    from websockets.exceptions import InvalidStatus
    from websockets.sync.client import connect

    port, _ = server
    url = f"ws://127.0.0.1:{port}/pty?agent=zzz&cwd={tmp_path}"
    with pytest.raises(InvalidStatus) as exc:
        connect(url, origin=PANEL)
    assert exc.value.response.status_code == 400


def test_websocket_from_panel_origin_is_accepted(server, tmp_path, monkeypatch):
    from websockets.sync.client import connect

    port, _ = server
    monkeypatch.setitem(pty_manager.INTERACTIVE_COMMANDS, "gemini", _shell())
    url = f"ws://127.0.0.1:{port}/pty?agent=gemini&cwd={tmp_path}"
    with connect(url, origin=PANEL):
        pass


def test_socket_is_closed_when_the_cli_exits(server, tmp_path, monkeypatch):
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    port, _ = server
    monkeypatch.setitem(pty_manager.INTERACTIVE_COMMANDS, "gemini", _exits_at_once())
    url = f"ws://127.0.0.1:{port}/pty?agent=gemini&cwd={tmp_path}"
    seen = []
    with connect(url, origin=PANEL) as ws:
        with pytest.raises(ConnectionClosed):
            # ConPTY reports the child's exit a few seconds late.
            while True:
                seen.append(ws.recv(timeout=25))
    assert any("CLI" in m for m in seen if isinstance(m, str))
