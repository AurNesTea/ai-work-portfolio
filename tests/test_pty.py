import importlib.util
from pathlib import Path


def _load_pty_manager():
    spec = importlib.util.spec_from_file_location(
        "pty_manager",
        Path(__file__).resolve().parents[1] / "panel" / "scripts" / "pty_manager.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_gemini_always_runs_agy():
    mod = _load_pty_manager()
    assert mod.get_agent_pty_command("gemini") == ["agy"]


def test_cursor_command_logged_in_vs_logged_out(monkeypatch):
    mod = _load_pty_manager()

    monkeypatch.setattr(mod, "is_agent_logged_in", lambda agent_id: True)
    assert mod.get_agent_pty_command("cursor") == ["agent"]

    monkeypatch.setattr(mod, "is_agent_logged_in", lambda agent_id: False)
    assert mod.get_agent_pty_command("cursor") == ["agent", "login"]


def test_claude_command_logged_in_vs_logged_out(monkeypatch):
    mod = _load_pty_manager()

    monkeypatch.setattr(mod, "is_agent_logged_in", lambda agent_id: True)
    assert mod.get_agent_pty_command("claude") == ["claude"]

    monkeypatch.setattr(mod, "is_agent_logged_in", lambda agent_id: False)
    assert mod.get_agent_pty_command("claude") == ["claude", "auth", "login"]


def test_codex_command_logged_in_vs_logged_out(monkeypatch):
    mod = _load_pty_manager()

    monkeypatch.setattr(mod, "is_agent_logged_in", lambda agent_id: True)
    assert mod.get_agent_pty_command("codex") == ["codex"]

    monkeypatch.setattr(mod, "is_agent_logged_in", lambda agent_id: False)
    assert mod.get_agent_pty_command("codex") == ["codex", "login"]


def test_websocket_frame_roundtrip():
    mod = _load_pty_manager()
    payload = b"test message with some length: hello pty!"
    frame = mod.encode_ws_frame(payload, opcode=1)

    import io
    # Server-to-client frame is unmasked, decode_ws_frame handles both masked and unmasked
    stream = io.BytesIO(frame)
    opcode, data = mod.decode_ws_frame(stream.read)
    assert opcode == 1
    assert data == payload


def test_pty_websocket_integration(tmp_path, monkeypatch):
    import json
    import sys
    import threading
    import time
    from http.server import HTTPServer
    import websockets.sync.client

    scripts_dir = str(Path(__file__).resolve().parents[1] / "panel" / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import pty_manager
    import snapshot_server

    monkeypatch.setitem(
        pty_manager.INTERACTIVE_COMMANDS,
        "gemini",
        ["cmd.exe"] if pty_manager.os.name == "nt" else ["/bin/sh"],
    )

    handler_cls = snapshot_server.make_handler(snapshot_server.ServerState(tmp_path))
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        url = f"ws://127.0.0.1:{port}/pty?agent=gemini&cwd={tmp_path}"
        with websockets.sync.client.connect(url) as ws:
            time.sleep(0.5)
            # Send input
            ws.send(json.dumps({"type": "input", "data": "echo PTY_TEST_SUCCESS\r\n"}))
            # Read output
            t0 = time.time()
            received = []
            while time.time() - t0 < 3:
                try:
                    chunk = ws.recv(timeout=0.3)
                    received.append(chunk)
                    if "PTY_TEST_SUCCESS" in chunk:
                        break
                except Exception:
                    pass
            full = "".join(received)
            assert "PTY_TEST_SUCCESS" in full
    finally:
        server.shutdown()

