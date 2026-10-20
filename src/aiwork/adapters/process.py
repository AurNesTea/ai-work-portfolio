import shutil
import subprocess
import sys
from pathlib import Path


def prepare_cli_argv(cmd: list[str]) -> list[str]:
    """Make CLI argv runnable under CreateProcess on Windows.

    ``agent`` / many CLIs resolve to ``*.cmd``; list-form ``subprocess`` without
    ``shell=True`` cannot launch those directly (WinError 2).

    Anything after the program name goes through cmd.exe's own parser, which cuts an
    argument at its first newline, expands ``%VAR%`` and caps the line at 8191 characters.
    Do not put free text (a prompt) in argv for these; pass it as ``input_text`` instead.
    """
    if sys.platform != "win32" or not cmd:
        return list(cmd)
    resolved = shutil.which(cmd[0]) or cmd[0]
    if Path(resolved).suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/c", *cmd]
    return list(cmd)


def _decode(data: bytes | str | None, errors: str) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors=errors)


def run_cli(
    cmd: list[str], *, input_text: str | None = None, **kwargs
) -> subprocess.CompletedProcess[str]:
    """Run an agent CLI and return text output.

    ``input_text`` is written to the child's stdin as UTF-8 *bytes*. Text-mode stdin would
    turn every ``\\n`` into ``\\r\\n`` on Windows, so the child would not get the prompt
    exactly as written. Without ``input_text`` the child gets a closed stdin: `codex exec`
    prints "Reading additional input from stdin..." and waits for EOF on an open pipe.
    """
    errors = kwargs.get("errors", "replace")
    if input_text is None:
        kwargs.setdefault("encoding", "utf-8")
        kwargs.setdefault("errors", "replace")
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        return subprocess.run(prepare_cli_argv(cmd), **kwargs)

    for key in ("text", "universal_newlines", "encoding", "errors", "stdin", "input"):
        kwargs.pop(key, None)
    try:
        proc = subprocess.run(
            prepare_cli_argv(cmd),
            input=input_text.encode("utf-8", errors="replace"),
            **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        exc.stdout = _decode(exc.stdout, errors)
        exc.stderr = _decode(exc.stderr, errors)
        raise
    return subprocess.CompletedProcess(
        proc.args,
        proc.returncode,
        _decode(proc.stdout, errors),
        _decode(proc.stderr, errors),
    )
