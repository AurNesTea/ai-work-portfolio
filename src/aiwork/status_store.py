import json
from pathlib import Path

from aiwork.models import RunStatus


def write_status(run_dir: Path, status: RunStatus) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "status.json"
    path.write_text(status.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_status(run_dir: Path) -> RunStatus:
    return RunStatus.model_validate_json(
        (run_dir / "status.json").read_text(encoding="utf-8")
    )


def set_current(runs_root: Path, run_id: str | None) -> Path:
    runs_root.mkdir(parents=True, exist_ok=True)
    path = runs_root / "current.json"
    if run_id is None:
        if path.exists():
            path.unlink()
        return path
    path.write_text(json.dumps({"run_id": run_id}, indent=2), encoding="utf-8")
    return path


def get_current(runs_root: Path) -> str | None:
    path = runs_root / "current.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["run_id"]
