from pathlib import Path

from aiwork.ledger import append_usage
from aiwork.models import UsageEvent
from aiwork.usage_report import summarize_run


def test_summarize_by_model(tmp_path: Path):
    run_dir = tmp_path / "r"
    run_dir.mkdir()
    append_usage(
        run_dir,
        UsageEvent(
            run_id="r",
            step_id="a",
            agent="cursor",
            model_requested="m",
            model_actual="A",
            input_uncached=1,
            cache_read=2,
            cache_write=0,
            output=3,
            dirty=True,
        ),
    )
    append_usage(
        run_dir,
        UsageEvent(
            run_id="r",
            step_id="b",
            agent="cursor",
            model_requested="m",
            model_actual="A",
            input_uncached=4,
            output=1,
        ),
    )
    summary = summarize_run(run_dir)
    assert summary["A"]["input_uncached"] == 5
    assert summary["A"]["output"] == 4
    assert summary["A"]["dirty"] == 1
    assert summary["A"]["events"] == 2
