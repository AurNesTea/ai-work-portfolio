import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from aiwork.adapters.process import prepare_cli_argv, run_cli


def test_prepare_cli_argv_passthrough_non_windows():
    with patch.object(sys, "platform", "linux"):
        assert prepare_cli_argv(["agent", "-p", "hi"]) == ["agent", "-p", "hi"]


def test_run_cli_gives_the_child_a_closed_stdin():
    # `codex exec` waits for EOF on an inherited open stdin; the child must get DEVNULL.
    seen: dict = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)

    with patch("aiwork.adapters.process.subprocess.run", fake_run):
        run_cli(["codex", "exec", "hi"], capture_output=True, text=True)
        assert seen["stdin"] is subprocess.DEVNULL
        run_cli(["codex", "exec", "hi"], stdin=subprocess.PIPE)  # an explicit choice wins
        assert seen["stdin"] is subprocess.PIPE


def test_prepare_cli_argv_wraps_cmd_on_windows(tmp_path: Path):
    fake = tmp_path / "agent.cmd"
    fake.write_text("@echo off\n", encoding="utf-8")
    with patch.object(sys, "platform", "win32"):
        with patch("aiwork.adapters.process.shutil.which", return_value=str(fake)):
            out = prepare_cli_argv(["agent", "--version"])
    assert out[:2] == ["cmd.exe", "/c"]
    assert out[2:] == ["agent", "--version"]
