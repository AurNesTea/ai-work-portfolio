import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from aiwork.adapters.base import AdapterResult
from aiwork.adapters.process import run_cli
from aiwork.effort import cursor_model_slug


@dataclass
class CursorParseResult:
    session_id: str | None
    model_actual: str
    input_uncached: int
    cache_read: int
    cache_write: int
    output: int
    dirty: bool
    # None when the text held no stream-json events at all; "" when it did but the call
    # never reached a `result` event.
    final_text: str | None = None
    error_text: str = ""


def parse_cursor_stream(text: str) -> CursorParseResult:
    model_actual = "unknown"
    session_id = None
    usage: dict = {}
    dirty = False
    saw_events = False
    final_text = ""
    error_text = ""
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        saw_events = True
        if obj.get("type") == "system" and obj.get("subtype") == "init":
            model_actual = obj.get("model") or model_actual
            session_id = obj.get("session_id") or session_id
        if obj.get("type") == "result":
            session_id = obj.get("session_id") or session_id
            usage = obj.get("usage") or {}
            # The `result` event is the agent's final answer. The `user` event before it
            # echoes the prompt and `tool_call` events carry file contents; neither is it.
            answer = obj.get("result")
            final_text = answer if isinstance(answer, str) else ""
            error_text = final_text if obj.get("is_error") else ""
        if obj.get("type") == "tool_call":
            tc = obj.get("tool_call") or {}
            if "taskToolCall" in tc:
                dirty = True
    return CursorParseResult(
        session_id=session_id,
        model_actual=model_actual,
        input_uncached=int(usage.get("inputTokens") or 0),
        cache_read=int(usage.get("cacheReadTokens") or 0),
        cache_write=int(usage.get("cacheWriteTokens") or 0),
        output=int(usage.get("outputTokens") or 0),
        dirty=dirty,
        final_text=final_text if saw_events else None,
        error_text=error_text,
    )


def build_cursor_command(
    *, model: str, force: bool = True, effort: str = "medium"
) -> list[str]:
    """argv for `agent -p`. The prompt is not in it: `run_cursor` sends it on stdin.

    On Windows `agent` is a .cmd shim, and cmd.exe cuts a prompt argument at its first
    newline (and still exits 0), so a multi-line prompt would silently lose all but line 1.
    """
    cmd = [
        "agent",
        "-p",
        "--output-format",
        "stream-json",
        "--model",
        cursor_model_slug(model, effort),
        "--trust",
    ]
    if force:
        cmd.append("--force")
    return cmd


def run_cursor(
    *,
    model: str,
    prompt: str,
    cwd: str,
    timeout_sec: int,
    env: dict | None = None,
    effort: str = "medium",
) -> AdapterResult:
    merged = {**os.environ, **(env or {})}
    mcp_src = merged.get("AIWORK_MCP_CONFIG")
    cursor_mcp = Path(cwd) / ".cursor" / "mcp.json"
    backup = Path(cwd) / ".cursor" / "mcp.json.aiwork-bak"
    restored = False
    if mcp_src and Path(mcp_src).is_file():
        cursor_mcp.parent.mkdir(parents=True, exist_ok=True)
        if cursor_mcp.exists():
            shutil.copy2(cursor_mcp, backup)
        shutil.copy2(mcp_src, cursor_mcp)
        restored = True
    try:
        cmd = build_cursor_command(model=model, force=True, effort=effort)
        proc = run_cli(
            cmd,
            input_text=prompt,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=merged,
        )
    finally:
        if restored:
            if backup.exists():
                shutil.move(str(backup), str(cursor_mcp))
            elif cursor_mcp.exists():
                # profile had empty/allowlist-only config; remove generated overlay
                pass
    parsed = parse_cursor_stream(proc.stdout)
    return AdapterResult(
        exit_code=proc.returncode,
        session_id=parsed.session_id,
        model_actual=parsed.model_actual,
        input_uncached=parsed.input_uncached,
        cache_read=parsed.cache_read,
        cache_write=parsed.cache_write,
        output=parsed.output,
        cost_usd=None,
        dirty=parsed.dirty,
        stdout=proc.stdout,
        stderr=proc.stderr,
        final_text=parsed.final_text,
        error_text=parsed.error_text,
    )
