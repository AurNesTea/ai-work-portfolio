from collections import defaultdict
from pathlib import Path

from aiwork.ledger import read_usage
from aiwork.models import UsageEvent


def summarize_usage(events: list[UsageEvent]) -> dict:
    by_model: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "input_uncached": 0,
            "cache_read": 0,
            "cache_write": 0,
            "output": 0,
            "dirty": 0,
            "events": 0,
        }
    )
    for ev in events:
        row = by_model[ev.model_actual]
        row["input_uncached"] += ev.input_uncached
        row["cache_read"] += ev.cache_read
        row["cache_write"] += ev.cache_write
        row["output"] += ev.output
        row["dirty"] += int(ev.dirty)
        row["events"] += 1
    return dict(by_model)


def summarize_run(run_dir: Path) -> dict:
    return summarize_usage(read_usage(run_dir))
