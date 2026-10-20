import json
import os

from aiwork.adapters.base import AdapterResult
from aiwork.adapters.process import run_cli
from aiwork.effort import cli_effort_args


def parse_gemini_json(text: str, *, model_fallback: str = "gemini") -> AdapterResult:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return AdapterResult(1, None, "gemini", 0, 0, 0, 0, None, False, text, "invalid json")
    response = obj.get("response")
    final_text = response if isinstance(response, str) else ""
    usage = obj.get("usage") or {}
    if "input_tokens" in usage or obj.get("conversation_id"):
        status = obj.get("status") or "SUCCESS"
        output = int(usage.get("output_tokens") or 0) + int(usage.get("thinking_tokens") or 0)
        return AdapterResult(
            exit_code=0 if status == "SUCCESS" else 1,
            session_id=obj.get("conversation_id"),
            model_actual=obj.get("model") or model_fallback,
            input_uncached=int(usage.get("input_tokens") or 0),
            cache_read=int(usage.get("cache_read_tokens") or 0),
            cache_write=int(usage.get("cache_write_tokens") or 0),
            output=output,
            cost_usd=None,
            dirty=False,
            stdout=text,
            stderr="",
            final_text=final_text,
            error_text=final_text if status != "SUCCESS" else "",
        )
    models = ((obj.get("stats") or {}).get("models")) or {}
    if not models:
        return AdapterResult(
            0, None, model_fallback, 0, 0, 0, 0, None, False, text, "",
            final_text=final_text,
        )
    # Prefer the model with the highest total token count when several present
    name, stats = max(
        models.items(),
        key=lambda kv: int((kv[1].get("tokens") or {}).get("total") or 0),
    )
    tokens = stats.get("tokens") or {}
    return AdapterResult(
        exit_code=0,
        session_id=None,
        model_actual=name,
        input_uncached=int(tokens.get("prompt") or 0),
        cache_read=int(tokens.get("cached") or 0),
        cache_write=0,
        output=int(tokens.get("candidates") or 0),
        cost_usd=None,
        dirty=False,
        stdout=text,
        stderr="",
        final_text=final_text,
    )


def build_gemini_command(*, model: str, prompt: str, effort: str = "medium") -> list[str]:
    cmd = [
        "agy",
        "--print",
        prompt,
        "--output-format",
        "json",
        "--model",
        model,
        "--dangerously-skip-permissions",
    ]
    cmd.extend(cli_effort_args("gemini", effort))
    return cmd


def run_gemini(
    *,
    model: str,
    prompt: str,
    cwd: str,
    timeout_sec: int,
    env: dict | None = None,
    effort: str = "medium",
) -> AdapterResult:
    cmd = build_gemini_command(model=model, prompt=prompt, effort=effort)
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
            proc.returncode, None, model, 0, 0, 0, 0, None, False, proc.stdout, proc.stderr
        )
    parsed = parse_gemini_json(proc.stdout, model_fallback=model)
    if proc.returncode != 0:
        parsed.exit_code = proc.returncode
    parsed.stderr = proc.stderr
    return parsed
