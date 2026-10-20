from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

# One path component, no separators or leading dot. run_id / step_id end up in
# runs/<run_id>/approvals/<step_id>.approved, so they must not be able to climb out.
_SAFE_ID = re.compile(r"\w[\w.-]{0,127}")


def _safe_id(value: object) -> bool:
    return isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None


def _spawn_aiwork(root: Path, args: list[str], *, timeout: int | None) -> dict:
    cmd = [sys.executable, "-m", "aiwork", *args]
    # A fire-and-forget run is never read or waited on, and PIPE handles close when this
    # function returns, so the child's final prints would hit a broken pipe. Its outcome
    # is in runs/<id>/status.json, not its stdio.
    stdio = subprocess.DEVNULL if timeout is None else subprocess.PIPE
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            stdout=stdio,
            stderr=stdio,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}
    if timeout is None:
        return {"ok": True, "detail": f"started pid={proc.pid}"}
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return {"ok": False, "detail": "timed out"}
    ok = proc.returncode == 0
    detail = (out or err or "").strip() or f"exit {proc.returncode}"
    return {"ok": ok, "detail": detail}


def run_workflow(root: Path, workflow: str) -> dict:
    rel = Path(workflow)
    if rel.is_absolute() or ".." in rel.parts:
        return {"ok": False, "detail": "workflow must be a relative path"}
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return {"ok": False, "detail": "workflow outside repo"}
    if not path.is_file() or path.suffix not in {".yaml", ".yml"}:
        return {"ok": False, "detail": f"not a workflow yaml: {rel}"}
    return _spawn_aiwork(
        root,
        ["run", str(rel), "--root", ".", "--workdir", ".", "--runs-root", "runs"],
        timeout=None,
    )


def continue_run(root: Path, workflow: str, run_id: str, re_resolve: bool = False) -> dict:
    if not _safe_id(run_id):
        return {"ok": False, "detail": "invalid run_id"}
    rel = Path(workflow)
    if rel.is_absolute() or ".." in rel.parts:
        return {"ok": False, "detail": "workflow must be a relative path"}
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return {"ok": False, "detail": "workflow outside repo"}
    if not path.is_file() or path.suffix not in {".yaml", ".yml"}:
        return {"ok": False, "detail": f"not a workflow yaml: {rel}"}
    status_path = root / "runs" / run_id / "status.json"
    if not status_path.is_file():
        return {"ok": False, "detail": "沒有可繼續的執行"}
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {"ok": False, "detail": "status.json 或 workflow 無法讀取"}
    if not isinstance(status, dict) or status.get("state") != "waiting":
        return {"ok": False, "detail": "沒有可繼續的執行"}
    if not isinstance(data, dict) or data.get("id") != status.get("workflow_id"):
        return {"ok": False, "detail": "workflow 與這次執行不符"}
    cmd_args = [
        "run",
        str(rel).replace("\\", "/"),
        "--root",
        ".",
        "--workdir",
        ".",
        "--runs-root",
        "runs",
        "--resume",
        run_id,
    ]
    if re_resolve:
        cmd_args.append("--re-resolve")
    return _spawn_aiwork(root, cmd_args, timeout=None)


def approve_step(root: Path, run_id: str, step_id: str) -> dict:
    if not _safe_id(run_id) or not _safe_id(step_id):
        return {"ok": False, "detail": "invalid run_id/step_id"}
    return _spawn_aiwork(
        root, ["approve", run_id, step_id, "--runs-root", "runs"], timeout=30
    )


def cancel_run(root: Path, run_id: str | None) -> dict:
    args = ["cancel", "--runs-root", "runs"]
    if run_id:
        if not _safe_id(run_id):
            return {"ok": False, "detail": "invalid run_id"}
        args.insert(1, run_id)
    return _spawn_aiwork(root, args, timeout=30)


def list_workflows(root: Path) -> list[str]:
    wf = root / "workflows"
    if not wf.is_dir():
        return []
    names = sorted(
        p.relative_to(root).as_posix()
        for p in wf.glob("*.yaml")
        if p.is_file()
    )
    names += sorted(
        p.relative_to(root).as_posix()
        for p in wf.glob("*.yml")
        if p.is_file() and p.as_posix() not in names
    )
    return names


def snapshot_plus(root: Path, selected: str | None) -> dict:
    from snapshot_server import build_snapshot

    snap = build_snapshot(root, selected)
    wfs = list_workflows(root)
    snap["workflows"] = wfs
    if not snap.get("workflow_steps") and wfs:
        for candidate in wfs:
            try:
                data = yaml.safe_load((root / candidate).read_text(encoding="utf-8"))
                if isinstance(data, dict) and "steps" in data:
                    snap["workflow_steps"] = [
                        s["id"] for s in data["steps"] if isinstance(s, dict) and "id" in s
                    ]
                    break
            except Exception:
                pass

    status = snap.get("status")
    dispatch_changed = False
    if isinstance(status, dict) and status.get("state") == "waiting":
        run_id = status.get("run_id") or snap.get("current_run_id") or snap.get("selected_run_id")
        if run_id:
            resolved_file = root / "runs" / run_id / "resolved.json"
            if resolved_file.is_file():
                try:
                    from aiwork.dispatch import (
                        load_resolved,
                        local_roles_path,
                        models_config_path,
                        roles_config_path,
                        sha256_file,
                    )

                    resolved = load_resolved(root / "runs" / run_id)
                    r_path = roles_config_path()
                    if "roles" in resolved.tables:
                        if not r_path.is_file() or sha256_file(r_path) != resolved.tables["roles"].sha256:
                            dispatch_changed = True
                    loc_path = local_roles_path()
                    if "roles_local" in resolved.tables:
                        if not loc_path.is_file() or sha256_file(loc_path) != resolved.tables["roles_local"].sha256:
                            dispatch_changed = True
                    elif loc_path.is_file():
                        dispatch_changed = True
                    m_path = models_config_path()
                    if "models" in resolved.tables:
                        if not m_path.is_file() or sha256_file(m_path) != resolved.tables["models"].sha256:
                            dispatch_changed = True
                except Exception:
                    pass
    snap["dispatch_changed"] = dispatch_changed
    return snap


