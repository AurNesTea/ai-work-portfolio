from pathlib import Path

from aiwork.adapters.cursor import parse_cursor_stream


def test_parse_cursor_usage_and_model():
    text = Path("tests/fixtures/cursor_result_success.jsonl").read_text(encoding="utf-8")
    parsed = parse_cursor_stream(text)
    assert parsed.session_id == "sess-1"
    assert parsed.model_actual == "Composer 2"
    assert parsed.input_uncached == 7
    assert parsed.cache_read == 100
    assert parsed.cache_write == 20
    assert parsed.output == 50
    assert parsed.dirty is False
