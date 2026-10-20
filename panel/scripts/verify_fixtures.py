"""Verify panel fixtures are readable the same way the Rust snapshot expects."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def main() -> None:
    current = json.loads((ROOT / "runs" / "current.json").read_text(encoding="utf-8"))
    run_id = current["run_id"]
    status = json.loads(
        (ROOT / "runs" / run_id / "status.json").read_text(encoding="utf-8")
    )
    assert status["state"] == "running"
    assert status["step_id"] == "step2"
    by_model: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "input_uncached": 0,
            "cache_read": 0,
            "cache_write": 0,
            "output": 0,
            "events": 0,
            "mismatch_events": 0,
        }
    )
    for line in (ROOT / "runs" / run_id / "usage_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        row = by_model[ev["model_actual"]]
        row["input_uncached"] += ev["input_uncached"]
        row["cache_read"] += ev["cache_read"]
        row["cache_write"] += ev["cache_write"]
        row["output"] += ev["output"]
        row["events"] += 1
        row["mismatch_events"] += int(ev.get("mismatch", False))
    totals = by_model["Composer 2.5"]
    assert totals["input_uncached"] == 180
    assert totals["output"] == 35
    assert totals["mismatch_events"] == 2
    print("fixture ok", run_id, status["state"], dict(by_model))


if __name__ == "__main__":
    main()
