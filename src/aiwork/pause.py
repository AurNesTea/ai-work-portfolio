import re

from aiwork.adapters.base import AdapterResult

_DECISION = "需要產品決定"
# The marker only counts at the start of a line (a little markdown noise in front is fine).
_DECISION_LINE = re.compile(r"^[\s>*_`#\-]*" + _DECISION)

_LOGIN = (
    "not logged in",
    "please log in",
    "please login",
    "login required",
    "authentication required",
    "401 unauthorized",
    "missing bearer",
)
_PERMISSION = (
    "permission denied",
    "access denied",
    "not authorized",
    "insufficient permission",
)
_QUOTA = (
    "pay-as-you-go",
    "pay as you go",
    "usage limit",
    "usage-based",
    "extra usage",
    "insufficient_quota",
    "quota exceeded",
    "credit balance",
    "out of credits",
    "monthly limit",
    "resource_exhausted",
)


def _line(text: str, needle: str) -> str:
    for line in text.splitlines():
        if needle.lower() in line.lower():
            return line.strip()[:240]
    compact = " ".join(text.split())
    return compact[:240]


def decision_problem(text: str | None) -> str | None:
    """The agent asked a human to decide: a line that starts with 需要產品決定.

    Pass the agent's own final answer. A transcript also holds the echoed prompt (which
    tells the agent how to write this marker), its reasoning, and tool output such as a
    file that happens to contain the phrase; none of those are a request to pause.
    """
    for line in (text or "").splitlines():
        match = _DECISION_LINE.match(line)
        if match:
            rest = line[match.end():].lstrip("：:").strip().strip("*_` ")
            return f"{_DECISION}：{rest}"[:240]
    return None


def needle_problem(text: str) -> str | None:
    """A pause is not a failure. A used-up monthly allowance does not continue on pay-as-you-go.

    Scans for the CLI's own login / permission / quota wording. Only feed it text the CLI
    wrote about its own failure (stderr, its error messages), never a whole transcript.
    """
    raw = text.strip()
    if not raw:
        return None
    lowered = raw.lower()
    for needle in _QUOTA:
        if needle in lowered:
            return f"月費額度已用完：不改走 pay-as-you-go。{_line(raw, needle)}"
    for needle in _LOGIN:
        if needle in lowered:
            return f"未登入：{_line(raw, needle)}"
    for needle in _PERMISSION:
        if needle in lowered:
            return f"權限不足：{_line(raw, needle)}"
    return None


# Kept for existing callers: scanning free text for the failure wording.
pause_problem = needle_problem


def step_pause_problem(result: AdapterResult) -> str | None:
    """Decide whether a finished CLI call should pause the run, and why.

    - The agent can always ask for a decision, in its own final answer.
    - A call that exited 0 can pause for nothing else: login, permission and quota wording
      inside a successful transcript is data the agent read, not a failure of the CLI.
    - A failed call is judged by what the CLI reported: stderr and its error messages.
    """
    answer = result.final_text if result.final_text is not None else result.stdout
    problem = decision_problem(answer)
    if problem or result.exit_code == 0:
        return problem
    parts = [result.stderr, result.error_text]
    if result.final_text is None:
        parts.append(result.stdout)  # output format unknown: nothing narrower to look at
    return needle_problem("\n".join(part for part in parts if part))
