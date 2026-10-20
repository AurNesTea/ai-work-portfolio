"""One SQLite ledger for token use across projects.

Dollars are not stored. List price is computed when the log is read.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from aiwork.models import UsageEvent

_SOURCES = frozenset({"run", "import", "manual"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_event (
  id INTEGER PRIMARY KEY,
  recorded_at TEXT NOT NULL,
  repo_root TEXT NOT NULL,
  run_id TEXT NOT NULL,
  workflow_id TEXT NOT NULL,
  step_id TEXT NOT NULL,
  agent TEXT NOT NULL,
  dispatch_role TEXT,
  model_requested TEXT NOT NULL,
  model_actual TEXT NOT NULL,
  effort TEXT NOT NULL,
  input_uncached INTEGER NOT NULL DEFAULT 0,
  cache_read INTEGER NOT NULL DEFAULT 0,
  cache_write INTEGER NOT NULL DEFAULT 0,
  output INTEGER NOT NULL DEFAULT 0,
  session_id TEXT,
  dirty INTEGER NOT NULL DEFAULT 0,
  mismatch INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'run',
  UNIQUE (repo_root, run_id, step_id, recorded_at)
);
CREATE INDEX IF NOT EXISTS idx_usage_event_recorded_at
  ON usage_event (recorded_at);
CREATE INDEX IF NOT EXISTS idx_usage_event_repo_recorded
  ON usage_event (repo_root, recorded_at);
CREATE INDEX IF NOT EXISTS idx_usage_event_model_recorded
  ON usage_event (model_actual, recorded_at);
"""


def usage_db_path() -> Path:
    """Path of the shared ledger. Tests set AIWORK_USAGE_DB."""
    override = os.environ.get("AIWORK_USAGE_DB")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data" / "usage.sqlite"


def insert_event(
    repo_root: Path,
    event: UsageEvent,
    workflow_id: str,
    *,
    source: str = "run",
    db_path: Path | None = None,
) -> bool:
    """Insert one step. A repeated key is ignored and returns False."""
    if source not in _SOURCES:
        raise ValueError(f"unknown usage source: {source}")
    with closing(_connect(db_path)) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO usage_event (
              recorded_at, repo_root, run_id, workflow_id, step_id,
              agent, dispatch_role, model_requested, model_actual, effort,
              input_uncached, cache_read, cache_write, output,
              session_id, dirty, mismatch, source
            ) VALUES (
              ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?,
              ?, ?, ?, ?,
              ?, ?, ?, ?
            )
            """,
            (
                event.recorded_at or "",
                _repo_key(repo_root),
                event.run_id,
                workflow_id,
                event.step_id,
                event.agent,
                event.dispatch_role,
                event.model_requested,
                event.model_actual,
                event.effort,
                event.input_uncached,
                event.cache_read,
                event.cache_write,
                event.output,
                event.session_id,
                int(event.dirty),
                int(event.mismatch),
                source,
            ),
        )
        conn.commit()
        return cur.rowcount == 1



def import_repo(repo_root: Path, db_path: Path | None = None) -> int:
    """Copy runs/*/usage_events.jsonl into the ledger. Returns new rows."""
    runs = Path(repo_root) / "runs"
    if not runs.is_dir():
        return 0
    added = 0
    for run_dir in runs.iterdir():
        if not run_dir.is_dir() or run_dir.name.startswith("."):
            continue
        added += _import_run(repo_root, run_dir, db_path)
    return added


def list_events(
    repo_root: Path | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """Return ledger rows. One repo, or every repo when repo_root is omitted."""
    sql = "SELECT * FROM usage_event"
    params: tuple[str, ...] = ()
    if repo_root is not None:
        sql += " WHERE repo_root = ?"
        params = (_repo_key(repo_root),)
    sql += " ORDER BY id"
    with closing(_connect(db_path)) as conn:
        found = conn.execute(sql, params).fetchall()
    return [dict(row) for row in found]


def record_run_event(run_dir: Path, event: UsageEvent) -> bool:
    """Store one runner event. run_dir is runs/<id>."""
    recorded = event.recorded_at or _started_at(run_dir) or ""
    stored = event.model_copy(update={"recorded_at": recorded})
    return insert_event(
        _repo_of_run(run_dir),
        stored,
        _workflow_id(run_dir),
        source="run",
    )


def _import_run(repo_root: Path, run_dir: Path, db_path: Path | None) -> int:
    path = run_dir / "usage_events.jsonl"
    if not path.is_file():
        return 0
    started = _started_at(run_dir) or ""
    workflow_id = _workflow_id(run_dir)
    added = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = _parse_event(line, started)
        if event is None:
            continue
        if insert_event(
            repo_root, event, workflow_id, source="import", db_path=db_path
        ):
            added += 1
    return added


def _parse_event(line: str, started: str) -> UsageEvent | None:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    if not raw.get("model_requested"):
        raw["model_requested"] = str(raw.get("model_actual") or "")
    if not raw.get("recorded_at"):
        raw["recorded_at"] = started
    try:
        return UsageEvent.model_validate(raw)
    except ValueError:
        return None


def _connect(db_path: Path | None) -> sqlite3.Connection:
    path = db_path or usage_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(usage_event)").fetchall()}
    if "dispatch_role" not in cols:
        conn.execute("ALTER TABLE usage_event ADD COLUMN dispatch_role TEXT;")
        conn.commit()
    return conn


def _repo_key(repo_root: Path) -> str:
    return str(Path(repo_root).resolve())


def _repo_of_run(run_dir: Path) -> Path:
    parent = run_dir.parent
    if parent.name == "runs":
        return parent.parent
    return parent


def _workflow_id(run_dir: Path) -> str:
    status = _read_status(run_dir)
    value = status.get("workflow_id") if status else None
    return value if isinstance(value, str) else ""


def _started_at(run_dir: Path) -> str:
    status = _read_status(run_dir)
    value = status.get("started_at") if status else None
    return value if isinstance(value, str) else ""


def _read_status(run_dir: Path) -> dict | None:
    path = run_dir / "status.json"
    if not path.is_file():
        return None
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(status, dict):
        return None
    return status
