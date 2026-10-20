import json
from pathlib import Path

import pytest
import yaml

from aiwork.adapters.base import AdapterResult
from aiwork.adapters.claude import build_claude_command
from aiwork.adapters.codex import build_codex_command
from aiwork.adapters.cursor import build_cursor_command
from aiwork.adapters.gemini import build_gemini_command
from aiwork.effort import recorded_effort
from aiwork.models import StepSpec
from aiwork.runner import _write_event
from aiwork.workflow import load_workflow


def _result() -> AdapterResult:
    return AdapterResult(
        exit_code=0,
        session_id=None,
        model_actual="m",
        input_uncached=0,
        cache_read=0,
        cache_write=0,
        output=0,
        cost_usd=None,
        dirty=False,
        stdout="",
        stderr="",
    )


def test_claude_command_passes_effort():
    cmd = build_claude_command(model="sonnet", prompt="hi", effort="high")
    assert cmd[cmd.index("--effort") + 1] == "high"


def test_codex_command_passes_reasoning_effort():
    cmd = build_codex_command(model="gpt-5.5", effort="low")
    assert "model_reasoning_effort=low" in cmd
    assert cmd[-1] == "-"  # the prompt is read from stdin


def test_cursor_composer_keeps_model_because_it_has_no_effort_level():
    cmd = build_cursor_command(model="composer-2", force=True, effort="high")
    assert cmd[cmd.index("--model") + 1] == "composer-2"
    assert "--effort" not in cmd


def test_cursor_puts_effort_in_model_override():
    cmd = build_cursor_command(model="gpt-5.5", force=True, effort="high")
    assert cmd[cmd.index("--model") + 1] == "gpt-5.5[effort=high]"


def test_cursor_replaces_existing_effort_suffix():
    cmd = build_cursor_command(
        model="claude-opus-5-thinking-high-fast", force=True, effort="low"
    )
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-thinking-low-fast"


def test_gemini_command_calls_agy_with_effort():
    cmd = build_gemini_command(model="gemini-2.5-pro", prompt="hi", effort="high")
    assert cmd[0] == "agy"
    assert cmd[cmd.index("--print") + 1] == "hi"
    assert cmd[cmd.index("--model") + 1] == "gemini-2.5-pro"
    assert cmd[cmd.index("--effort") + 1] == "high"
    assert "-m" not in cmd


@pytest.mark.parametrize(
    ("agent", "model", "asked", "booked"),
    [
        ("cursor", "composer-2", "high", "medium"),
        ("cursor", "gpt-5.5", "high", "high"),
        ("gemini", "gemini-2.5-pro", "low", "low"),
        ("claude", "sonnet", "high", "high"),
        ("codex", "gpt-5.5", "low", "low"),
    ],
)
def test_ledger_books_the_effort_the_cli_will_use(agent, model, asked, booked, tmp_path: Path):
    assert recorded_effort(agent, asked, model=model) == booked
    step = StepSpec(
        id="s",
        agent=agent,
        model=model,
        prompt_file="p.md",
        effort=asked,
    )
    _write_event(tmp_path, run_id="r", step=step, result=_result())
    row = json.loads((tmp_path / "usage_events.jsonl").read_text(encoding="utf-8"))
    assert row["effort"] == booked


def test_step_defaults_effort_medium_and_zero_retries():
    step = StepSpec(id="s", agent="cursor", model="m", prompt_file="p.md")
    assert step.effort == "medium"
    assert step.max_retries == 0


def test_workflow_loads_effort_and_retry_allowance(tmp_path: Path):
    brief = tmp_path / "briefs" / "b.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("b", encoding="utf-8")
    prompt = tmp_path / "prompts" / "p.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("p", encoding="utf-8")
    wf = {
        "id": "w",
        "brief_path": "briefs/b.md",
        "steps": [
            {
                "id": "s",
                "agent": "claude",
                "model": "sonnet",
                "prompt_file": "prompts/p.md",
                "effort": "high",
                "max_retries": 2,
            }
        ],
    }
    path = tmp_path / "workflows" / "w.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(wf), encoding="utf-8")
    spec = load_workflow(path, root=tmp_path)
    assert spec.steps[0].effort == "high"
    assert spec.steps[0].max_retries == 2
