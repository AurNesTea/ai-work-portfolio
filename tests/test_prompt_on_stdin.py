"""Cursor and Codex get the prompt on stdin: cmd.exe cuts an argv prompt at its first newline."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aiwork.adapters.codex import run_codex
from aiwork.adapters.cursor import run_cursor
from aiwork.adapters.process import run_cli

HARD_PROMPT = "\n".join(
    [
        "first line",
        '中文第二行：測試 %USERNAME% !BANG! "quoted" & amp ^ caret | pipe < lt > gt',
        "",
        "line after a blank line",
        "x" * 20000,  # far past cmd.exe's 8191-character limit
        "last line TOKEN-7QX4Z",
        "",  # ends with a newline
    ]
)


def _fake_run_cli(seen: dict):
    def fake(cmd, **kwargs):
        seen["cmd"] = cmd
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return fake


def test_cursor_sends_the_prompt_on_stdin_not_in_argv(monkeypatch, tmp_path: Path):
    seen: dict = {}
    monkeypatch.setattr("aiwork.adapters.cursor.run_cli", _fake_run_cli(seen))
    prompt = "line one\nline two\nTOKEN"

    run_cursor(model="composer-2", prompt=prompt, cwd=str(tmp_path), timeout_sec=5)

    assert seen["input_text"] == prompt
    assert not any("line one" in arg or "TOKEN" in arg for arg in seen["cmd"])
    assert seen["cmd"][-1] == "--force"


def test_codex_reads_the_prompt_from_stdin_via_dash(monkeypatch, tmp_path: Path):
    seen: dict = {}
    monkeypatch.setattr("aiwork.adapters.codex.run_cli", _fake_run_cli(seen))
    prompt = "line one\nline two\nTOKEN"

    run_codex(model="gpt-5.5", prompt=prompt, cwd=str(tmp_path), timeout_sec=5)

    assert seen["input_text"] == prompt
    assert seen["cmd"][-1] == "-"
    assert not any("line one" in arg or "TOKEN" in arg for arg in seen["cmd"])


def test_run_cli_writes_stdin_bytes_without_turning_lf_into_crlf():
    echo = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"]
    proc = run_cli(echo, input_text="a\nb\n\n中文\n", capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert proc.stdout == "a\nb\n\n中文\n"  # a text-mode pipe would have returned \r\n


def test_run_cli_with_input_returns_decoded_text_and_accepts_adapter_kwargs():
    child = [sys.executable, "-c", "import sys; sys.stderr.buffer.write('警告'.encode()); print('ok')"]
    proc = run_cli(
        child, input_text="", capture_output=True, text=True, timeout=60, cwd=os.getcwd(), env=dict(os.environ)
    )
    assert isinstance(proc.stdout, str) and isinstance(proc.stderr, str)
    assert proc.stdout.strip() == "ok"
    assert proc.stderr == "警告"


def test_run_cli_timeout_with_input_carries_text_not_bytes():
    child = [sys.executable, "-c", "import sys,time; sys.stdout.write('partial'); sys.stdout.flush(); time.sleep(30)"]
    with pytest.raises(subprocess.TimeoutExpired) as exc:
        run_cli(child, input_text="x", capture_output=True, text=True, timeout=2)
    assert isinstance(exc.value.stdout, str)


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe shims only exist on Windows")
def test_prompt_survives_a_cmd_shim_byte_for_byte(tmp_path: Path, monkeypatch):
    # A stand-in for agent.cmd / codex.cmd: a .cmd that records its argv and its stdin bytes.
    (tmp_path / "capture.py").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "here = Path(__file__).parent\n"
        "(here / 'stdin.bin').write_bytes(sys.stdin.buffer.read())\n"
        "(here / 'argv.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "sys.stdout.buffer.write('結果 ok\\n'.encode('utf-8'))\n",
        encoding="utf-8",
    )
    (tmp_path / "fakeagent.cmd").write_text(
        f'@echo off\r\n"{sys.executable}" "%~dp0capture.py" %*\r\n', encoding="utf-8"
    )
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    proc = run_cli(
        ["fakeagent", "-p", "--model", "m"],
        input_text=HARD_PROMPT,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "stdin.bin").read_bytes() == HARD_PROMPT.encode("utf-8")
    assert json.loads((tmp_path / "argv.json").read_text(encoding="utf-8")) == ["-p", "--model", "m"]
    assert "結果 ok" in proc.stdout
