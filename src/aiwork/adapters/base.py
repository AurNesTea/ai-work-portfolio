from dataclasses import dataclass


@dataclass
class AdapterResult:
    exit_code: int
    session_id: str | None
    model_actual: str
    input_uncached: int
    cache_read: int
    cache_write: int
    output: int
    cost_usd: float | None
    dirty: bool
    stdout: str
    stderr: str
    # The agent's own final answer. ``None`` means the adapter does not understand its
    # stdout (so the runner falls back to the raw text); a string, even an empty one, means
    # the adapter parsed it. stdout also holds the echoed prompt, the agent's reasoning and
    # every tool result, none of which are the agent speaking to the runner.
    final_text: str | None = None
    # Messages the CLI itself reported as errors (an auth failure, a failed turn). Only
    # meaningful when the call failed: a CLI may report recovered errors on a good run.
    error_text: str = ""
