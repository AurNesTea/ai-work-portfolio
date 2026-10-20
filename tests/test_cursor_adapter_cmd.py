from aiwork.adapters.cursor import build_cursor_command


def test_build_cursor_command_includes_model_and_print():
    cmd = build_cursor_command(model="composer-2", force=True)
    assert cmd[0] in ("agent", "cursor-agent")
    assert "-p" in cmd or "--print" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--model" in cmd
    assert "composer-2" in cmd


def test_build_cursor_command_ends_with_a_flag_because_the_prompt_goes_on_stdin():
    assert build_cursor_command(model="composer-2", force=True)[-1] == "--force"
    assert build_cursor_command(model="composer-2", force=False)[-1] == "--trust"
