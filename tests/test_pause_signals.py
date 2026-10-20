"""Pause only on signals the CLI or the agent really sent, not on text that merely appears.

Real finding behind these tests: run 8af1029f6dd6 step1 succeeded ("smoke step 1 ok."), but a
`grep` tool result in its transcript contained the words "login required", so scanning the
whole stdout paused it as "未登入". A prompt that tells the agent how to write 需要產品決定
echoes that phrase back too, so such a step would pause on every run.
"""
import json
import subprocess
from pathlib import Path

from aiwork.adapters.base import AdapterResult
from aiwork.adapters.claude import parse_claude_json
from aiwork.adapters.codex import parse_codex_stream
from aiwork.adapters.cursor import parse_cursor_stream
from aiwork.adapters.gemini import parse_gemini_json
from aiwork.models import StepSpec, WorkflowSpec
from aiwork.pause import decision_problem, needle_problem, step_pause_problem
from aiwork.runner import run_workflow
from aiwork.status_store import read_status

FIXTURES = Path(__file__).parent / "fixtures"
REAL_STREAM = (FIXTURES / "cursor_stream_grep_login_required.jsonl").read_text(encoding="utf-8")
PASS = 'python -c "import sys; sys.exit(0)"'


def _cursor_stream(*, prompt="", thinking="", tool_output="", answer="", is_error=False) -> str:
    """A transcript in the shape Cursor's stream-json really has."""
    events = [
        {"type": "system", "subtype": "init", "model": "Composer 2.5", "session_id": "s1"},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}},
        {"type": "thinking", "subtype": "delta", "text": thinking},
        {
            "type": "tool_call",
            "subtype": "completed",
            "tool_call": {"readToolCall": {"result": {"success": {"content": tool_output}}}},
        },
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": answer}]}},
        {
            "type": "result",
            "subtype": "success",
            "is_error": is_error,
            "result": answer,
            "session_id": "s1",
            "usage": {"inputTokens": 1, "outputTokens": 1},
        },
    ]
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"


def _cursor_result(stdout: str, code: int = 0, stderr: str = "") -> AdapterResult:
    parsed = parse_cursor_stream(stdout)
    return AdapterResult(
        code, parsed.session_id, parsed.model_actual, 0, 0, 0, 0, None, False, stdout, stderr,
        final_text=parsed.final_text, error_text=parsed.error_text,
    )


# ---- the false positives -------------------------------------------------------------

def test_real_stream_with_a_grep_hit_on_login_required_does_not_pause():
    assert "login required" in REAL_STREAM.lower()
    # the old rule: scan the whole transcript
    assert (needle_problem(REAL_STREAM) or "").startswith("未登入")

    result = _cursor_result(REAL_STREAM)

    assert result.final_text == "Checking the smoke-test context to confirm step 1.\nsmoke step 1 ok."
    assert step_pause_problem(result) is None


def test_phrases_in_prompt_thinking_and_tool_output_do_not_pause_a_successful_step():
    stream = _cursor_stream(
        prompt="If you need a human, reply with a line that starts with 需要產品決定： and the question.",
        thinking="The file mentions 需要產品決定 but that is only data.",
        tool_output="需要產品決定：舊 API\nPermission denied\nPlease log in\nYou've hit your usage limit",
        answer="done",
    )
    assert (needle_problem(stream) or "") != ""  # the old rule paused this
    assert step_pause_problem(_cursor_result(stream)) is None


def test_a_successful_step_never_pauses_for_failure_wording_even_in_its_answer():
    answer = "Fixed the Permission denied bug; note the usage limit docs say please log in first."
    assert step_pause_problem(_cursor_result(_cursor_stream(answer=answer))) is None


# ---- the real signal ------------------------------------------------------------------

def test_agent_asking_for_a_decision_pauses_even_though_the_prompt_mentions_the_marker():
    question = "Should the exported CSV keep the legacy column order, or switch to alphabetical?"
    stream = _cursor_stream(
        prompt="Reply with one line that starts with 需要產品決定： followed by the question.",
        answer=f"需要產品決定：{question}",
    )
    problem = step_pause_problem(_cursor_result(stream))
    assert problem == f"需要產品決定：{question}"


def test_decision_marker_must_start_a_line_but_tolerates_markdown():
    assert decision_problem("**需要產品決定：保留舊欄位？**") == "需要產品決定：保留舊欄位？"
    assert decision_problem("Notes first.\n> 需要產品決定：A or B") == "需要產品決定：A or B"
    assert decision_problem("- 需要產品決定: 用哪個") == "需要產品決定：用哪個"
    assert decision_problem("I would normally write 需要產品決定 here, but not now") is None
    assert decision_problem("") is None
    assert decision_problem(None) is None


# ---- real failures still pause ----------------------------------------------------------

def test_cursor_logged_out_pauses_from_stderr():
    result = _cursor_result(
        "", code=1,
        stderr="Error: Authentication required. Please run 'agent login' first, or set CURSOR_API_KEY environment variable.",
    )
    assert (step_pause_problem(result) or "").startswith("未登入：")


def test_claude_not_logged_in_pauses_from_its_error_result():
    text = json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in · Please run /login"})
    result = parse_claude_json(text)
    result.exit_code = 1
    assert result.error_text == "Not logged in · Please run /login"
    assert (step_pause_problem(result) or "").startswith("未登入：")


CODEX_401 = "\n".join(
    json.dumps(e)
    for e in [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "i0", "type": "error", "message": "Skill descriptions were shortened"}},
        {"type": "error", "message": "Reconnecting... 2/5 (unexpected status 401 Unauthorized: Missing bearer or basic authentication in header, url: wss://api.openai.com/v1/responses)"},
        {"type": "error", "message": "unexpected status 401 Unauthorized: Missing bearer or basic authentication in header, url: https://api.openai.com/v1/responses"},
        {"type": "turn.failed", "error": {"message": "unexpected status 401 Unauthorized: Missing bearer or basic authentication in header"}},
    ]
)


def test_codex_401_unauthorized_pauses_as_not_logged_in():
    result = parse_codex_stream(CODEX_401)
    result.exit_code = 1
    result.stderr = "ERROR codex_api::endpoint::responses_websocket: HTTP error: 401 Unauthorized"
    assert "401 Unauthorized" in result.error_text
    assert (step_pause_problem(result) or "").startswith("未登入：")
    assert needle_problem("missing bearer or basic authentication") is not None


def test_codex_recovered_reconnect_errors_do_not_pause_a_successful_run():
    stream = "\n".join(
        json.dumps(e)
        for e in [
            {"type": "error", "message": "Reconnecting... 1/5 (unexpected status 401 Unauthorized)"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "all good"}},
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
        ]
    )
    result = parse_codex_stream(stream)  # exit_code 0
    assert result.final_text == "all good"
    assert step_pause_problem(result) is None


def test_used_up_allowance_on_a_failed_call_still_pauses():
    result = AdapterResult(1, None, "m", 0, 0, 0, 0, None, False, "", "You've hit your usage limit. Enable pay-as-you-go", final_text="")
    assert (step_pause_problem(result) or "").startswith("月費額度已用完")


def test_failed_structured_call_ignores_wording_that_is_only_in_the_transcript():
    # Cursor died (exit 1) with no result event, after reading a file that says "login required".
    stream = _cursor_stream(tool_output="login required").split('{"type": "result"')[0]
    result = _cursor_result(stream, code=1, stderr="boom")
    assert result.final_text == ""  # structured output, but it never reached a result
    assert step_pause_problem(result) is None


def test_unknown_output_format_falls_back_to_the_raw_text():
    result = AdapterResult(1, None, "m", 0, 0, 0, 0, None, False, "Please log in", "")
    assert result.final_text is None
    assert (step_pause_problem(result) or "").startswith("未登入：")
    ok = AdapterResult(0, None, "m", 0, 0, 0, 0, None, False, "需要產品決定：要保留舊 API 嗎", "")
    assert step_pause_problem(ok) == "需要產品決定：要保留舊 API 嗎"


# ---- parsers fill the two fields ------------------------------------------------------

def test_cursor_parser_separates_final_answer_from_the_transcript():
    parsed = parse_cursor_stream(_cursor_stream(prompt="PROMPT", tool_output="FILE", answer="ANSWER"))
    assert parsed.final_text == "ANSWER"
    assert parsed.error_text == ""
    failed = parse_cursor_stream(_cursor_stream(answer="Error: boom", is_error=True))
    assert failed.error_text == "Error: boom"
    assert parse_cursor_stream("not json at all").final_text is None
    assert parse_cursor_stream("").final_text is None


def test_codex_parser_takes_the_last_agent_message_as_final():
    stream = "\n".join(
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": t}})
        for t in ("thinking out loud", "final answer")
    )
    assert parse_codex_stream(stream).final_text == "final answer"
    assert parse_codex_stream("garbage").final_text is None


def test_claude_and_gemini_parsers_expose_the_answer():
    claude = parse_claude_json((FIXTURES / "claude_result.json").read_text(encoding="utf-8"))
    assert claude.final_text == "ok" and claude.error_text == ""
    gemini = parse_gemini_json((FIXTURES / "gemini_result.json").read_text(encoding="utf-8"))
    assert gemini.final_text == "ok"
    agy = parse_gemini_json((FIXTURES / "agy_result.json").read_text(encoding="utf-8"))
    assert agy.final_text == "ok" and agy.error_text == ""
    failed = parse_gemini_json(json.dumps({"conversation_id": "c", "status": "ERROR", "response": "quota exceeded"}))
    assert failed.exit_code == 1 and failed.error_text == "quota exceeded"


# ---- through the runner ---------------------------------------------------------------

def _two_step_workflow(tmp_path: Path) -> WorkflowSpec:
    (tmp_path / "b.md").write_text("brief", encoding="utf-8")
    steps = []
    for sid in ("a", "b"):
        (tmp_path / f"{sid}.md").write_text(f"prompt {sid}", encoding="utf-8")
        steps.append(
            StepSpec(id=sid, agent="cursor", model="m", prompt_file=str(tmp_path / f"{sid}.md"), test_command=PASS)
        )
    return WorkflowSpec(id="demo", brief_path=str(tmp_path / "b.md"), steps=steps)


def test_runner_continues_past_a_transcript_that_merely_mentions_the_phrases(tmp_path: Path):
    calls: list[str] = []

    def run_fn(**kwargs):
        calls.append(kwargs["step"].id)
        return _cursor_result(REAL_STREAM)

    run_dir = run_workflow(
        workflow=_two_step_workflow(tmp_path), runs_root=tmp_path / "runs",
        workdir=tmp_path, root=tmp_path, adapters={"cursor": run_fn},
    )
    assert read_status(run_dir).state == "succeeded"
    assert calls == ["a", "b"]


def test_runner_pauses_at_the_step_whose_answer_asks_for_a_decision(tmp_path: Path):
    def run_fn(**kwargs):
        if kwargs["step"].id == "a":
            return _cursor_result(_cursor_stream(prompt="write 需要產品決定： if unsure", answer="done"))
        return _cursor_result(_cursor_stream(prompt="write 需要產品決定： if unsure", answer="需要產品決定：A 還是 B？"))

    run_dir = run_workflow(
        workflow=_two_step_workflow(tmp_path), runs_root=tmp_path / "runs",
        workdir=tmp_path, root=tmp_path, adapters={"cursor": run_fn},
    )
    status = read_status(run_dir)
    assert status.state == "waiting"
    assert status.step_id == "b"
    assert status.last_error == "需要產品決定：A 還是 B？"
    assert (run_dir / "steps" / "a" / "ok").exists()


def test_a_timeout_whose_command_line_holds_the_marker_is_a_failure_not_a_pause(tmp_path: Path):
    def run_fn(**kwargs):
        raise subprocess.TimeoutExpired(["claude", "-p", "write 需要產品決定：x if unsure"], timeout=1)

    run_dir = run_workflow(
        workflow=_two_step_workflow(tmp_path), runs_root=tmp_path / "runs",
        workdir=tmp_path, root=tmp_path, adapters={"cursor": run_fn},
    )
    assert read_status(run_dir).state == "failed"
