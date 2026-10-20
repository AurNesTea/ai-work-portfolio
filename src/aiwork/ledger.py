from pathlib import Path

from aiwork.models import UsageEvent


def append_usage(run_dir: Path, event: UsageEvent) -> Path:
    path = run_dir / "usage_events.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(event.model_dump_json() + "\n")
    return path


def read_usage(run_dir: Path) -> list[UsageEvent]:
    path = run_dir / "usage_events.jsonl"
    if not path.exists():
        return []
    return [
        UsageEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
