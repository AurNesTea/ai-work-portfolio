from aiwork.models import AgentName, EffortName

_WITH_EFFORT_FLAG = frozenset({"claude", "codex", "gemini"})
_LEVELS = ("extra-high", "xhigh", "minimal", "medium", "none", "high", "low", "max")


def cli_effort_args(agent: AgentName, effort: EffortName) -> list[str]:
    if agent in ("claude", "gemini"):
        return ["--effort", effort]
    if agent == "codex":
        return ["-c", f"model_reasoning_effort={effort}"]
    return []


def _split_fast(model: str) -> tuple[str, str]:
    if model.endswith("-fast"):
        return model[: -len("-fast")], "-fast"
    return model, ""


def _replace_level(base: str, effort: str) -> str | None:
    for level in _LEVELS:
        for pattern in (f"-thinking-{level}", f"-{level}-thinking", f"-{level}"):
            if base.endswith(pattern):
                head = base[: -len(pattern)]
                if pattern.startswith("-thinking-"):
                    return f"{head}-thinking-{effort}"
                if pattern.endswith("-thinking"):
                    return f"{head}-{effort}-thinking"
                return f"{head}-{effort}"
    return None


def cursor_model_slug(model: str, effort: EffortName) -> str:
    """Cursor has no --effort flag. Levels live in the model slug."""
    base, fast = _split_fast(model)
    if base == "auto" or base.startswith("composer"):
        return model
    replaced = _replace_level(base, effort)
    if replaced is not None:
        return replaced + fast
    return f"{model}[effort={effort}]"


def recorded_effort(agent: AgentName, effort: EffortName, *, model: str = "") -> EffortName:
    if agent in _WITH_EFFORT_FLAG:
        return effort
    if agent == "cursor" and cursor_model_slug(model, effort) != model:
        return effort
    return "medium"
