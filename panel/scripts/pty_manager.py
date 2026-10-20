"""Native PTY session manager and WebSocket handler for aiwork panel."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import agents
except ImportError:
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import agents

WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def is_agent_logged_in(agent_id: str) -> bool:
    """Check if the given agent is logged in. Gemini always returns True."""
    if agent_id == "gemini":
        return not agents._is_agent_logged_out("gemini")
    status_argv = agents.STATUS_ARGV.get(agent_id)
    if not status_argv:
        return True
    program = status_argv[0]
    if shutil.which(program) is None:
        return False
    try:
        proc = agents._run(status_argv)
        text = f"{proc.stdout}\n{proc.stderr}"
        return agents._logged_in(agent_id, proc.returncode, text)
    except Exception:
        return False


INTERACTIVE_COMMANDS: dict[str, list[str]] = {
    "cursor": ["agent"],
    "claude": ["claude"],
    "codex": ["codex"],
    "gemini": ["agy"],
}

LOGIN_COMMANDS: dict[str, list[str]] = {
    "cursor": ["agent", "login"],
    "claude": ["claude", "auth", "login"],
    "codex": ["codex", "login"],
    "gemini": ["agy"],
}


def get_agent_pty_command(agent_id: str) -> list[str]:
    """Return the interactive or login command for the specified agent.

    - Gemini: always ["agy"].
    - Cursor: ["agent"] if logged in, else ["agent", "login"].
    - Claude: ["claude"] if logged in, else ["claude", "auth", "login"].
    - Codex: ["codex"] if logged in, else ["codex", "login"].
    """
    if agent_id == "gemini":
        return INTERACTIVE_COMMANDS["gemini"]

    logged_in = is_agent_logged_in(agent_id)
    if logged_in:
        return INTERACTIVE_COMMANDS.get(
            agent_id, ["cmd.exe"] if os.name == "nt" else ["/bin/sh"]
        )
    return LOGIN_COMMANDS.get(
        agent_id, ["cmd.exe"] if os.name == "nt" else ["/bin/sh"]
    )


def encode_ws_frame(payload: bytes, opcode: int = 1) -> bytes:
    """Encode an RFC 6455 unmasked WebSocket frame (server-to-client)."""
    b0 = 0x80 | (opcode & 0x0F)
    length = len(payload)
    if length <= 125:
        header = bytes([b0, length])
    elif length <= 65535:
        header = struct.pack("!BBH", b0, 126, length)
    else:
        header = struct.pack("!BBQ", b0, 127, length)
    return header + payload


def decode_ws_frame(reader) -> tuple[int | None, bytes | None]:
    """Decode an RFC 6455 masked WebSocket frame from reader callable."""
    hdr = reader(2)
    if not hdr or len(hdr) < 2:
        return None, None
    b0, b1 = hdr[0], hdr[1]
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    if length == 126:
        ext = reader(2)
        if not ext or len(ext) < 2:
            return None, None
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = reader(8)
        if not ext or len(ext) < 8:
            return None, None
        length = struct.unpack("!Q", ext)[0]

    if masked:
        mask = reader(4)
        if not mask or len(mask) < 4:
            return None, None
        raw = reader(length)
        if not raw or len(raw) < length:
            return None, None
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(raw))
    else:
        payload = reader(length)
    return opcode, payload


def spawn_pty_process(argv: list[str], cwd: str, rows: int = 24, cols: int = 80):
    """Spawn a local PTY process.

    On Windows: uses winpty (Windows Pseudo Console / ConPTY).
    On POSIX: uses ptyprocess or pty.
    """
    cmd0 = argv[0]
    resolved = shutil.which(cmd0)
    if not resolved:
        raise FileNotFoundError(f"找不到執行檔: {cmd0}")

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"

    if os.name == "nt":
        import winpty

        ext = Path(resolved).suffix.lower()
        if ext in {".cmd", ".bat"}:
            full_argv = ["cmd.exe", "/c", resolved, *argv[1:]]
        else:
            full_argv = [resolved, *argv[1:]]
        return winpty.PtyProcess.spawn(
            full_argv, cwd=cwd, env=env, dimensions=(rows, cols)
        )
    else:
        import ptyprocess

        full_argv = [resolved, *argv[1:]]
        return ptyprocess.PtyProcess.spawn(
            full_argv, cwd=cwd, env=env, dimensions=(rows, cols)
        )


def handle_pty_websocket(handler, default_root: Path, parsed) -> None:
    """Upgrade connection to WebSocket and manage bidirectional PTY stream."""
    key = handler.headers.get("Sec-WebSocket-Key")
    if not key:
        handler.send_error(400, "Missing Sec-WebSocket-Key")
        return

    qs = parse_qs(parsed.query)
    agent_id = (qs.get("agent") or ["cursor"])[0]
    # Only the four known CLIs. The cmd.exe / sh fallbacks below are not for the wire:
    # an unknown id must never become a raw shell.
    if agent_id not in INTERACTIVE_COMMANDS:
        handler.send_error(400, "Unknown agent")
        handler.close_connection = True
        return

    # WebSocket Handshake
    acc = base64.b64encode(hashlib.sha1((key + WS_MAGIC).encode()).digest()).decode()
    handler.send_response(101)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", acc)
    handler.end_headers()

    cwd_param = (qs.get("cwd") or [None])[0]
    cwd = (
        str(Path(cwd_param).resolve())
        if cwd_param and Path(cwd_param).is_dir()
        else str(default_root.resolve())
    )
    cols = int((qs.get("cols") or [80])[0])
    rows = int((qs.get("rows") or [24])[0])

    sock = handler.connection
    write_lock = threading.Lock()

    def send_ws(text_or_bytes: str | bytes, opcode: int = 1):
        payload = (
            text_or_bytes.encode("utf-8", errors="replace")
            if isinstance(text_or_bytes, str)
            else text_or_bytes
        )
        frame = encode_ws_frame(payload, opcode=opcode)
        with write_lock:
            try:
                handler.wfile.write(frame)
                handler.wfile.flush()
            except Exception:
                pass

    is_gemini = (agent_id == "gemini")
    already_logged_in = is_gemini or is_agent_logged_in(agent_id)
    is_login_flow = not already_logged_in
    initial_cmd = (
        INTERACTIVE_COMMANDS.get(
            agent_id, ["cmd.exe"] if os.name == "nt" else ["/bin/sh"]
        )
        if already_logged_in
        else LOGIN_COMMANDS.get(
            agent_id, ["cmd.exe"] if os.name == "nt" else ["/bin/sh"]
        )
    )

    proc_holder: dict[str, object] = {
        "pty": None,
        "rows": rows,
        "cols": cols,
    }
    stop_event = threading.Event()

    try:
        pty_proc = spawn_pty_process(initial_cmd, cwd=cwd, rows=rows, cols=cols)
        proc_holder["pty"] = pty_proc
    except FileNotFoundError as err:
        send_ws(f"\r\n\x1b[31m[錯誤] {err}\x1b[0m\r\n請確認已安裝並加入系統 PATH。\r\n")
        handler.close_connection = True
        return
    except Exception as exc:
        send_ws(f"\r\n\x1b[31m[啟動失敗] {exc}\x1b[0m\r\n")
        handler.close_connection = True
        return

    # Reader thread: PTY -> WebSocket client
    def reader_loop():
        nonlocal is_login_flow
        while not stop_event.is_set():
            active_proc = proc_holder.get("pty")
            if active_proc is None:
                break
            try:
                chunk = active_proc.read(1024)
                if not chunk:
                    raise EOFError
                send_ws(chunk, opcode=1)
            except (EOFError, OSError):
                if is_login_flow:
                    # Login process completed. Verify whether login succeeded.
                    login_ok = False
                    for _ in range(3):
                        time.sleep(0.4)
                        if is_agent_logged_in(agent_id):
                            login_ok = True
                            break
                    if login_ok:
                        is_login_flow = False
                        send_ws("\r\n\x1b[32m[登入成功，於專案目錄啟動互動模式...]\x1b[0m\r\n\r\n")
                        try:
                            status_msg = json.dumps({
                                "type": "agent_status",
                                "agent": agent_id,
                                "state": "logged_in",
                            })
                            send_ws(status_msg, opcode=1)
                        except Exception:
                            pass
                        inter_cmd = INTERACTIVE_COMMANDS.get(
                            agent_id, ["cmd.exe"] if os.name == "nt" else ["/bin/sh"]
                        )
                        try:
                            new_proc = spawn_pty_process(
                                inter_cmd,
                                cwd=cwd,
                                rows=int(proc_holder.get("rows", 24)),
                                cols=int(proc_holder.get("cols", 80)),
                            )
                            proc_holder["pty"] = new_proc
                            continue
                        except Exception as exc:
                            send_ws(f"\r\n\x1b[31m[啟動互動模式失敗] {exc}\x1b[0m\r\n")
                            break
                    else:
                        send_ws("\r\n\x1b[33m[登入未完成或已關閉，未啟動互動模式]\x1b[0m\r\n")
                        break
                else:
                    break
            except Exception:
                break
        send_ws("\r\n\x1b[90m[CLI 處理程序已關閉]\x1b[0m\r\n")
        stop_event.set()
        # Close the socket too: the main thread is parked in recv(), and a client that
        # still sees an open socket keeps showing a live terminal for a dead CLI.
        send_ws(struct.pack("!H", 1000), opcode=8)
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    t = threading.Thread(target=reader_loop, daemon=True)
    t.start()

    # Main thread: WebSocket client -> PTY
    def exact_read(n: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    return None
                buf.extend(chunk)
            except Exception:
                return None
        return bytes(buf)

    try:
        while not stop_event.is_set():
            opcode, payload = decode_ws_frame(exact_read)
            if opcode is None or opcode == 8:  # close frame
                break
            elif opcode == 9:  # ping
                send_ws(payload or b"", opcode=10)
            elif opcode == 1:  # text
                text = (payload or b"").decode("utf-8", errors="replace")
                active_proc = proc_holder.get("pty")
                if text.startswith("{"):
                    try:
                        msg = json.loads(text)
                        mtype = msg.get("type")
                        if mtype == "input":
                            if active_proc:
                                active_proc.write(msg.get("data", ""))
                            continue
                        elif mtype == "resize":
                            r = int(msg.get("rows", 24))
                            c = int(msg.get("cols", 80))
                            proc_holder["rows"] = r
                            proc_holder["cols"] = c
                            if active_proc:
                                active_proc.setwinsize(r, c)
                            continue
                    except Exception:
                        pass
                if active_proc:
                    active_proc.write(text)
            elif opcode == 2:  # binary
                active_proc = proc_holder.get("pty")
                if active_proc:
                    active_proc.write((payload or b"").decode("utf-8", errors="replace"))
    except Exception:
        pass
    finally:
        stop_event.set()
        active_proc = proc_holder.get("pty")
        if active_proc is not None:
            try:
                active_proc.terminate()
            except Exception:
                pass
        handler.close_connection = True
