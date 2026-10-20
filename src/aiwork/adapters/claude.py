import json
import os

from aiwork.adapters.base import AdapterResult
from aiwork.adapters.process import run_cli
from aiwork.effort import cli_effort_args


def parse_claude_json(text: str) -> AdapterResult:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return AdapterResult(1, None, "claude", 0, 0, 0, 0, None, False, text, "invalid json")
    usage = obj.get("usage") or {}
    model_usage = obj.get("modelUsage") or {}
    model_actual = next(iter(model_usage.keys()), "claude")
    result_text = obj.get("result")
    final_text = result_text if isinstance(result_text, str) else ""
    return AdapterResult(
        exit_code=0 if not obj.get("is_error") else 1,
        session_id=obj.get("session_id"),
        model_actual=model_actual,
        input_uncached=int(usage.get("input_tokens") or 0),
        cache_read=int(usage.get("cache_read_input_tokens") or 0),
        cache_write=int(usage.get("cache_creation_input_tokens") or 0),
        output=int(usage.get("output_tokens") or 0),
        cost_usd=obj.get("total_cost_usd"),
        dirty=False,
        stdout=text,
        stderr="",
        final_text=final_text,
        # e.g. "Not logged in · Please run /login" arrives as the result of an is_error call
        error_text=final_text if obj.get("is_error") else "",
    )


def build_claude_command(*, model: str, prompt: str, effort: str = "medium") -> list[str]:
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--model",
        model,
    ]
    cmd.extend(cli_effort_args("claude", effort))
    return cmd


def run_claude(
    *,
    model: str,
    prompt: str,
    cwd: str,
    timeout_sec: int,
    env: dict | None = None,
    effort: str = "medium",
) -> AdapterResult:
    cmd = build_claude_command(model=model, prompt=prompt, effort=effort)
    proc = run_cli(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env={**os.environ, **(env or {})},
    )
    if not proc.stdout.strip():
        return AdapterResult(
            proc.returncode,
            None,
            model,
            0,
            0,
            0,
            0,
            None,
            False,
            proc.stdout,
            proc.stderr,
        )
    parsed = parse_claude_json(proc.stdout)
    if proc.returncode != 0:
        parsed.exit_code = proc.returncode
    parsed.stderr = proc.stderr
    return parsed
