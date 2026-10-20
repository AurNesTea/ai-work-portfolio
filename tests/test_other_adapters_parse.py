import json
from pathlib import Path

from aiwork.adapters.claude import parse_claude_json
from aiwork.adapters.codex import parse_codex_stream
from aiwork.adapters.gemini import parse_gemini_json


def test_parse_claude_fixture():
    text = Path("tests/fixtures/claude_result.json").read_text(encoding="utf-8")
    r = parse_claude_json(text)
    assert r.session_id == "claude-sess"
    assert r.input_uncached == 10
    assert r.cache_read == 100
    assert r.cache_write == 20
    assert r.output == 5
    assert r.cost_usd == 0.012
    assert r.model_actual == "claude-sonnet"


def test_parse_codex_fixture():
    text = Path("tests/fixtures/codex_turn_completed.jsonl").read_text(encoding="utf-8")
    r = parse_codex_stream(text)
    # fixture usage: input 11 (of which 9 cached), output 4 (of which 2 reasoning)
    assert r.input_uncached == 2
    assert r.cache_read == 9
    assert r.output == 4
    assert r.input_uncached + r.cache_read == 11


def test_parse_codex_never_goes_negative_when_cached_exceeds_input():
    line = '{"type":"turn.completed","usage":{"input_tokens":5,"cached_input_tokens":9,"output_tokens":1}}'
    r = parse_codex_stream(line)
    assert r.input_uncached == 0
    assert r.cache_read == 9


def test_parse_gemini_fixture():
    text = Path("tests/fixtures/gemini_result.json").read_text(encoding="utf-8")
    r = parse_gemini_json(text)
    assert r.model_actual == "gemini-2.5-flash"
    assert r.input_uncached == 8
    assert r.cache_read == 1
    assert r.output == 3


def test_parse_agy_result_uses_conversation_usage():
    text = Path("tests/fixtures/agy_result.json").read_text(encoding="utf-8")
    r = parse_gemini_json(text, model_fallback="gemini-3.8-flash-high")
    assert r.session_id == "conv-1"
    assert r.model_actual == "gemini-3.8-flash-high"
    assert r.input_uncached == 10
    assert r.cache_read == 3
    assert r.output == 6
    assert r.exit_code == 0
