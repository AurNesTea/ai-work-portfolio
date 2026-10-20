from datetime import datetime, timezone
from pathlib import Path

from aiwork.models import RunStatus
from aiwork.status_store import get_current, read_status, set_current, write_status


def test_status_roundtrip(tmp_path: Path):
    now = datetime.now(timezone.utc).isoformat()
    st = RunStatus(
        run_id="r1",
        workflow_id="w",
        state="running",
        step_id="s1",
        pid=1,
        started_at=now,
        updated_at=now,
    )
    write_status(tmp_path / "r1", st)
    assert read_status(tmp_path / "r1").state == "running"
    set_current(tmp_path, "r1")
    assert get_current(tmp_path) == "r1"
    set_current(tmp_path, None)
    assert get_current(tmp_path) is None
