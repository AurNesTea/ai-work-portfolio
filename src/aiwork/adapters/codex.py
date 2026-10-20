import json
import os

from aiwork.adapters.base import AdapterResult
from aiwork.adapters.process import run_cli
from aiwork.effort import cli_effort_args


def parse_codex_stream(text: str, *, model_fallback: str = "codex") -> AdapterResult:
    usage = {}
    model_actual = model_fallback
    saw_events = False
    final_text = ""
    errors: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        saw_events = True
        kind = obj.get("type")
        if kind == "turn.completed":
            usage = obj.get("usage") or {}
        if obj.get("model"):
            model_actual = obj["model"]
        if kind == "item.completed":
            item = obj.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                final_text = item["text"]  # the last one is the final answer
        elif kind == "error" and isinstance(obj.get("message"), str):
            errors.append(obj["message"])
        elif kind == "turn.failed":
            message = (obj.get("error") or {}).get("message")
            if isinstance(message, str):
                errors.append(message)
    # Codex counts cached tokens inside input_tokens and reasoning tokens inside
    # output_tokens (its own total_tokens is input + output). Adding them on top would
    # bill the cached prompt at the full input price as well as the cache-read price.
    cached = int(usage.get("cached_input_tokens") or 0)
    return AdapterResult(
        exit_code=0,
        session_id=None,
        model_actual=model_actual,
        input_uncached=max(int(usage.get("input_tokens") or 0) - cached, 0),
        cache_read=cached,
        cache_write=0,
        output=int(usage.get("output_tokens") or 0),
        cost_usd=None,
        dirty=False,
        stdout=text,
        stderr="",
        final_text=final_text if saw_events else None,
        # `error` events also carry recovered "Reconnecting..." notices, so this is only
        # meaningful when the call failed; the runner only reads it then.
        error_text="\n".join(errors),
    )


def build_codex_command(*, model: str, effort: str = "medium") -> list[str]:
    """argv for `codex exec`. The prompt is not in it: the trailing ``-`` makes Codex read
    it from stdin, which `run_codex` fills.

    On Windows `codex` is a .cmd shim, and cmd.exe cuts a prompt argument at its first
    newline, so a multi-line prompt would silently lose all but line 1.
    """
    cmd = ["codex", "exec", "--json", "--model", model]
    cmd.extend(cli_effort_args("codex", effort))
    cmd.append("-")
    return cmd


def run_codex(
    *,
    model: str,
    prompt: str,
    cwd: str,
    timeout_sec: int,
    env: dict | None = None,
    effort: str = "medium",
) -> AdapterResult:
    cmd = build_codex_command(model=model, effort=effort)
    proc = run_cli(
        cmd,
        input_text=prompt,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env={**os.environ, **(env or {})},
    )
    parsed = parse_codex_stream(proc.stdout, model_fallback=model)
    parsed.exit_code = proc.returncode
    parsed.stderr = proc.stderr
    return parsed
