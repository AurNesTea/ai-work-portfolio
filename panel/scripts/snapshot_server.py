"""Read-only snapshot HTTP server for panel browser-dev / verify (Tauri-compatible DTO)."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import yaml

try:
    import aiwork
except ImportError:
    repo_src = Path(__file__).resolve().parents[2] / "src"
    if str(repo_src) not in sys.path:
        sys.path.insert(0, str(repo_src))

from aiwork.dispatch import (
    CLI_BY_AGENT,
    MODEL_ID_RE,
    VALID_AGENTS,
    _parse_roles_dict,
    check_models_catalog,
    load_models_catalog,
    load_roles,
    local_roles_path,
    models_config_path,
    roles_config_path,
    sha256_file,
    validate_roles,
)
from aiwork.packs import (
    PackError,
    PackSecurityError,
    PackValidationError,
    ROLE_ID_RE,
    apply_packs,
    commit_pack,
    disable_pack,
    enable_pack,
    find_role_definition,
    get_role_delivery_status,
    list_packs,
    load_machine_profile,
    load_probe_results,
    packs_status,
    run_probe,
    save_local_role,
    scan_skills_pool,
    stage_upload,
    undo_packs,
)
from actions import approve_step, cancel_run, continue_run, run_workflow, snapshot_plus
from agents import agent_rows, start_agent_login, start_agent_logout
from http_guard import origin_allowed, request_allowed
from pty_manager import handle_pty_websocket
from usage_log import collect_usage_log


def _read_json(path: Path):
    """The runner rewrites these files while the panel polls; a torn read is not an error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summarize_usage(run_dir: Path) -> dict:
    path = run_dir / "usage_events.jsonl"
    by_model: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "input_uncached": 0,
            "cache_read": 0,
            "cache_write": 0,
            "output": 0,
            "dirty": 0,
            "events": 0,
            "mismatch_events": 0,
        }
    )
    if not path.is_file():
        return {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:  # last line still being appended
            continue
        if not isinstance(ev, dict):
            continue
        row = by_model[ev.get("model_actual") or "unknown"]
        row["input_uncached"] += int(ev.get("input_uncached") or 0)
        row["cache_read"] += int(ev.get("cache_read") or 0)
        row["cache_write"] += int(ev.get("cache_write") or 0)
        row["output"] += int(ev.get("output") or 0)
        row["dirty"] += int(bool(ev.get("dirty")))
        row["mismatch_events"] += int(bool(ev.get("mismatch")))
        row["events"] += 1
    return dict(by_model)


def list_history(runs: Path, limit: int = 20) -> list[dict]:
    items: list[dict] = []
    if not runs.is_dir():
        return items
    for child in runs.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        status_path = child / "status.json"
        if not status_path.is_file():
            continue
        status = _read_json(status_path)
        if not isinstance(status, dict) or not all(
            k in status for k in ("run_id", "state", "workflow_id", "updated_at")
        ):
            continue
        items.append(
            {
                "run_id": status["run_id"],
                "state": status["state"],
                "workflow_id": status["workflow_id"],
                "updated_at": status["updated_at"],
            }
        )
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return items[:limit]


def get_workflow_steps(repo_root: Path, workflow_id: str | None) -> list[str]:
    if not workflow_id:
        return []
    wf_dir = repo_root / "workflows"
    if not wf_dir.is_dir():
        return []
    import yaml

    for candidate in [wf_dir / f"{workflow_id}.yaml", wf_dir / f"{workflow_id}.yml"]:
        if candidate.is_file():
            try:
                data = yaml.safe_load(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "steps" in data:
                    return [
                        s["id"]
                        for s in data["steps"]
                        if isinstance(s, dict) and "id" in s
                    ]
            except Exception:
                pass
    for f in sorted(wf_dir.glob("*.y*ml")):
        if f.is_file():
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
                if (
                    isinstance(data, dict)
                    and data.get("id") == workflow_id
                    and "steps" in data
                ):
                    return [
                        s["id"]
                        for s in data["steps"]
                        if isinstance(s, dict) and "id" in s
                    ]
            except Exception:
                pass
    return []


def build_snapshot(repo_root: Path, selected_run_id: str | None) -> dict:
    if not repo_root.is_dir():
        return {
            "repo_root": str(repo_root),
            "current_run_id": None,
            "selected_run_id": None,
            "status": None,
            "usage_by_model": {},
            "usage_log": [],
            "history": [],
            "workflow_steps": [],
            "error": f"repo root is not a directory: {repo_root}",
        }
    runs = repo_root / "runs"
    current = None
    current_path = runs / "current.json"
    if current_path.is_file():
        current_doc = _read_json(current_path)
        current = current_doc.get("run_id") if isinstance(current_doc, dict) else None
    history = list_history(runs)
    usage_log = collect_usage_log(repo_root)
    selected = selected_run_id or current or (history[0]["run_id"] if history else None)
    status = None
    usage: dict = {}
    if selected:
        status_path = runs / selected / "status.json"
        if status_path.is_file():
            doc = _read_json(status_path)
            status = doc if isinstance(doc, dict) else None
        usage = summarize_usage(runs / selected)
    workflow_steps: list[str] = []
    if status and status.get("workflow_id"):
        workflow_steps = get_workflow_steps(repo_root, status.get("workflow_id"))
    elif history:
        workflow_steps = get_workflow_steps(repo_root, history[0].get("workflow_id"))
    return {
        "repo_root": str(repo_root),
        "current_run_id": current,
        "selected_run_id": selected,
        "status": status,
        "usage_by_model": usage,
        "usage_log": usage_log,
        "history": history,
        "workflow_steps": workflow_steps,
        "error": None,
    }


class ServerState:
    def __init__(self, root: Path) -> None:
        self.root = root


def make_handler(state: ServerState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _cors_headers(self) -> None:
            origin = self.headers.get("Origin")
            if origin and origin_allowed(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _guard(self) -> bool:
            """Refuse cross-site pages and rebound hostnames before doing any work."""
            if request_allowed(self.headers):
                return True
            self.close_connection = True  # a request body, if any, is left unread
            self._json(403, {"ok": False, "detail": "forbidden origin"})
            return False

        def do_OPTIONS(self) -> None:  # noqa: N802
            if not self._guard():
                return
            self.send_response(204)
            self._cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if not self._guard():
                return
            root = state.root
            parsed = urlparse(self.path)
            if parsed.path == "/pty":
                handle_pty_websocket(self, root, parsed)
                return
            if parsed.path == "/agents":
                self._json(200, {"agents": agent_rows()})
                return
            if parsed.path == "/roles":
                try:
                    roles, tables_meta = load_roles()
                    catalog, _, _ = load_models_catalog()
                    errors, warnings = validate_roles(roles, catalog)
                    etags = {k: v.sha256 for k, v in tables_meta.items()}
                    cli_status = {
                        r_id: bool(shutil.which(CLI_BY_AGENT.get(r.agent, r.agent)))
                        for r_id, r in roles.items()
                    }
                    roles_data = {}
                    for r_id, r in roles.items():
                        role_file = find_role_definition(r_id)
                        defined_str, delivery_str = get_role_delivery_status(role_file)
                        roles_data[r_id] = {
                            "agent": r.agent,
                            "model": r.model,
                            "effort": r.effort or "medium",
                            "description": r.description,
                            "source": r.source,
                            "cli": CLI_BY_AGENT.get(r.agent, r.agent),
                            "cli_in_path": cli_status[r_id],
                            "defined": defined_str,
                            "delivery": delivery_str,
                        }
                    self._json(200, {
                        "ok": True,
                        "roles": roles_data,
                        "tables": {k: v.model_dump() for k, v in tables_meta.items()},
                        "etags": etags,
                        "warnings": warnings,
                        "errors": errors,
                    })
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return
            if parsed.path == "/models":
                try:
                    catalog, mpath, msha = load_models_catalog()
                    self._json(200, {
                        "ok": True,
                        "models": catalog,
                        "etag": msha,
                        "path": str(mpath),
                    })
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return
            if parsed.path == "/library":
                try:
                    profile = load_machine_profile()
                    packs = list_packs(libraries=profile.libraries)
                    packs_data = []
                    for p in packs:
                        packs_data.append({
                            "id": p.id,
                            "name": p.name,
                            "description": p.description,
                            "version": p.version,
                            "enabled": p.id in profile.enabled_packs,
                            "has_scripts": p.has_scripts,
                            "path": str(p.path) if p.path else None,
                            "items": [
                                {
                                    "kind": item.kind,
                                    "name": item.name,
                                    "path": str(item.path),
                                    "sha256": item.sha256,
                                    "has_scripts": item.has_scripts,
                                }
                                for item in p.items
                            ],
                        })
                    self._json(200, {
                        "ok": True,
                        "packs": packs_data,
                        "libraries": profile.libraries,
                        "enabled_packs": profile.enabled_packs,
                    })
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return
            if parsed.path == "/machine":
                try:
                    st = packs_status()
                    st["probe"] = load_probe_results()
                    self._json(200, {
                        "ok": True,
                        "machine": st,
                    })
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return
            if parsed.path == "/skills":
                try:
                    skills = scan_skills_pool()
                    self._json(200, {
                        "ok": True,
                        "skills": skills,
                    })
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return
            if parsed.path != "/snapshot":
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query)
            selected = (qs.get("selected_run_id") or [None])[0]
            try:
                payload = snapshot_plus(root, selected)
            except Exception as exc:  # noqa: BLE001 - report instead of dropping the connection
                self._json(500, {"ok": False, "detail": f"snapshot failed: {exc}"})
                return
            self._json(200, payload)

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard():
                return
            root = state.root
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            max_limit = 5 * 1024 * 1024 if parsed.path == "/library/upload" else 256 * 1024
            if length > max_limit:
                discarded = 0
                while discarded < length and discarded < 6 * 1024 * 1024:
                    chunk = self.rfile.read(min(65536, length - discarded))
                    if not chunk:
                        break
                    discarded += len(chunk)
                self.close_connection = True
                limit_str = "5 MB" if max_limit >= 1024 * 1024 else "256 KB"
                self._json(413, {"ok": False, "detail": f"payload too large (max {limit_str})"})
                return
            raw = self.rfile.read(length) if length else b""
            if parsed.path == "/library/upload":
                content_type = self.headers.get("Content-Type", "")
                try:
                    if "application/json" in content_type:
                        try:
                            upload_data = json.loads(raw.decode("utf-8") or "{}")
                        except Exception:
                            self._json(400, {"ok": False, "detail": "invalid json"})
                            return
                        if "content_base64" in upload_data or "data" in upload_data:
                            b64_str = upload_data.get("content_base64") or upload_data.get("data")
                            file_bytes = base64.b64decode(b64_str)
                            fname = upload_data.get("filename", "upload.zip")
                        elif "content" in upload_data:
                            file_bytes = str(upload_data["content"]).encode("utf-8")
                            fname = upload_data.get("filename", "role.md")
                        else:
                            self._json(400, {"ok": False, "detail": "missing file data or content in json"})
                            return
                        upload_id, file_list, has_scripts, warning = stage_upload(file_bytes, filename=fname)
                    elif "multipart/form-data" in content_type:
                        boundary = None
                        for param in content_type.split(";"):
                            param = param.strip()
                            if param.startswith("boundary="):
                                boundary = param[9:].strip('"')
                                break
                        if not boundary:
                            self._json(400, {"ok": False, "detail": "missing boundary in multipart"})
                            return
                        parts = raw.split(b"--" + boundary.encode())
                        found_file = False
                        fname = "upload.zip"
                        file_bytes = b""
                        for part in parts:
                            if b"Content-Disposition" in part:
                                header_part, _, body_part = part.partition(b"\r\n\r\n")
                                body_data = body_part.rstrip(b"\r\n-")
                                m = re.search(r'filename="([^"]+)"', header_part.decode("latin1", "replace"))
                                if m:
                                    fname = m.group(1)
                                    file_bytes = body_data
                                    found_file = True
                                    break
                        if not found_file:
                            file_bytes = raw
                        upload_id, file_list, has_scripts, warning = stage_upload(file_bytes, filename=fname)
                    else:
                        fname = "upload.zip" if raw.startswith(b"PK\x03\x04") else "upload.bin"
                        upload_id, file_list, has_scripts, warning = stage_upload(raw, filename=fname)

                    self._json(200, {
                        "ok": True,
                        "upload_id": upload_id,
                        "files": file_list,
                        "has_scripts": has_scripts,
                        "warning": warning,
                    })
                except (PackSecurityError, PackValidationError) as exc:
                    self._json(400, {"ok": False, "detail": str(exc)})
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "detail": "invalid json"})
                return
            if parsed.path == "/roles":
                target = str(data.get("target") or "shared")
                base_etag = data.get("base_etag")
                roles_input = data.get("roles")
                if not isinstance(roles_input, dict):
                    self._json(400, {"ok": False, "detail": "roles must be a mapping"})
                    return
                if target == "shared":
                    target_path = roles_config_path()
                elif target == "local":
                    target_path = local_roles_path()
                else:
                    self._json(400, {"ok": False, "detail": "invalid target: must be shared or local"})
                    return

                current_sha = sha256_file(target_path) if target_path.is_file() else None
                if base_etag is not None and current_sha is not None and base_etag != current_sha:
                    self._json(409, {"ok": False, "detail": "檔案已被修改，請重新載入 (conflict)"})
                    return
                if base_etag is not None and current_sha is None and base_etag != "":
                    self._json(409, {"ok": False, "detail": "檔案已被修改，請重新載入 (conflict)"})
                    return

                try:
                    parsed_roles = _parse_roles_dict(roles_input, target, target_path)
                    catalog, _, _ = load_models_catalog()
                    errs, _ = validate_roles(parsed_roles, catalog)
                    if errs:
                        self._json(400, {"ok": False, "detail": "; ".join(errs)})
                        return
                except Exception as exc:
                    self._json(400, {"ok": False, "detail": str(exc)})
                    return

                if target == "local" and target_path.is_file():
                    bak_path = target_path.with_suffix(".yaml.bak")
                    bak_path.write_bytes(target_path.read_bytes())

                target_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = target_path.with_suffix(".tmp")
                raw_out = {
                    "version": 1,
                    "roles": {
                        r_id: {
                            "agent": r.agent,
                            "model": r.model,
                            **({"effort": r.effort} if r.effort else {}),
                            "description": r.description,
                        }
                        for r_id, r in parsed_roles.items()
                    },
                }
                tmp_path.write_text(yaml.dump(raw_out, allow_unicode=True, sort_keys=False), encoding="utf-8")
                os.replace(tmp_path, target_path)
                self._json(200, {"ok": True, "new_etag": sha256_file(target_path)})
                return

            if parsed.path == "/models":
                base_etag = data.get("base_etag")
                models_input = data.get("models")
                if not isinstance(models_input, dict):
                    self._json(400, {"ok": False, "detail": "models must be a mapping"})
                    return
                target_path = models_config_path()
                current_sha = sha256_file(target_path) if target_path.is_file() else None
                if base_etag is not None and current_sha is not None and base_etag != current_sha:
                    self._json(409, {"ok": False, "detail": "檔案已被修改，請重新載入 (conflict)"})
                    return

                cleaned_models: dict[str, list[dict[str, str]]] = {}
                for agent, mlist in models_input.items():
                    if agent not in VALID_AGENTS:
                        self._json(400, {"ok": False, "detail": f"invalid agent: {agent}"})
                        return
                    if not isinstance(mlist, list):
                        self._json(400, {"ok": False, "detail": f"models for {agent} must be a list"})
                        return
                    cleaned_list = []
                    for item in mlist:
                        if isinstance(item, str):
                            mid = item
                            note = None
                        elif isinstance(item, dict) and "id" in item:
                            mid = str(item["id"])
                            note = item.get("note")
                        else:
                            self._json(400, {"ok": False, "detail": f"invalid model item for {agent}: {item}"})
                            return
                        if not MODEL_ID_RE.match(mid):
                            self._json(400, {"ok": False, "detail": f"invalid model id: {mid}"})
                            return
                        entry = {"id": mid}
                        if note:
                            entry["note"] = str(note)
                        cleaned_list.append(entry)
                    cleaned_models[agent] = cleaned_list

                target_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = target_path.with_suffix(".tmp")
                raw_out = {
                    "version": 1,
                    "models": cleaned_models,
                }
                tmp_path.write_text(yaml.dump(raw_out, allow_unicode=True, sort_keys=False), encoding="utf-8")
                os.replace(tmp_path, target_path)
                self._json(200, {"ok": True, "new_etag": sha256_file(target_path)})
                return

            if parsed.path == "/models/check":
                try:
                    result = check_models_catalog()
                    self._json(200, {"ok": True, "result": result})
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return

            if parsed.path == "/library/commit":
                upload_id = str(data.get("upload_id") or "").strip()
                pack_id = str(data.get("pack_id") or "").strip()
                replace = bool(data.get("replace", False))
                if not upload_id or not pack_id:
                    self._json(400, {"ok": False, "detail": "upload_id and pack_id are required"})
                    return
                try:
                    target_path = commit_pack(upload_id, pack_id, replace=replace)
                    self._json(200, {
                        "ok": True,
                        "pack_id": pack_id,
                        "path": str(target_path),
                    })
                except PackValidationError as exc:
                    self._json(400, {"ok": False, "detail": str(exc)})
                except PackError as exc:
                    if "already exists" in str(exc):
                        self._json(409, {"ok": False, "detail": str(exc)})
                    else:
                        self._json(400, {"ok": False, "detail": str(exc)})
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return

            if parsed.path == "/role":
                role_id = str(data.get("id") or "").strip()
                description = str(data.get("description") or "").strip()
                principles = str(data.get("principles") or data.get("body") or "").strip()
                skills = data.get("skills") or []
                if not role_id:
                    self._json(400, {"ok": False, "detail": "role id is required"})
                    return
                if not isinstance(skills, list):
                    self._json(400, {"ok": False, "detail": "skills must be a list"})
                    return
                try:
                    target_path = save_local_role(
                        role_id=role_id,
                        description=description,
                        principles=principles,
                        skills=[str(s) for s in skills],
                    )
                    self._json(200, {
                        "ok": True,
                        "id": role_id,
                        "path": str(target_path),
                    })
                except PackSecurityError as exc:
                    self._json(403, {"ok": False, "detail": str(exc)})
                except (PackValidationError, PackError) as exc:
                    self._json(400, {"ok": False, "detail": str(exc)})
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return

            if parsed.path == "/machine/enable":
                pack_id = str(data.get("pack_id") or "").strip()
                if not pack_id:
                    self._json(400, {"ok": False, "detail": "pack_id is required"})
                    return
                enabled = data.get("enabled", True)
                action = str(data.get("action") or "").lower()
                try:
                    if enabled is False or action == "disable":
                        profile = disable_pack(pack_id)
                    else:
                        profile = enable_pack(pack_id)
                    self._json(200, {
                        "ok": True,
                        "pack_id": pack_id,
                        "enabled": pack_id in profile.enabled_packs,
                        "enabled_packs": profile.enabled_packs,
                    })
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return

            if parsed.path == "/machine/apply":
                dry_run = bool(data.get("dry_run", True))
                replace = bool(data.get("replace", False))
                packs = data.get("packs")
                try:
                    profile = load_machine_profile()
                    packs_to_apply = packs if packs else profile.enabled_packs
                    res = apply_packs(packs=packs_to_apply, dry_run=dry_run, replace=replace, profile=profile)
                    if dry_run:
                        self._json(200, {
                            "ok": True,
                            "dry_run": True,
                            "plans": res.plans,
                        })
                    else:
                        self._json(200, {
                            "ok": True,
                            "dry_run": False,
                            "applied_count": len(res.applied_entries),
                            "applied": [e.model_dump() for e in res.applied_entries],
                        })
                except PackError as exc:
                    self._json(400, {"ok": False, "detail": str(exc)})
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return

            if parsed.path == "/machine/undo":
                packs = data.get("packs")
                try:
                    res = undo_packs(pack_ids=packs)
                    self._json(200, {
                        "ok": True,
                        "removed": res.removed,
                        "restored": res.restored,
                        "modified": res.modified,
                        "missing": res.missing,
                    })
                except PackError as exc:
                    self._json(400, {"ok": False, "detail": str(exc)})
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return

            if parsed.path == "/machine/probe":
                agent = data.get("agent")
                if agent and agent not in ("cursor", "claude", "gemini"):
                    self._json(400, {"ok": False, "detail": f"invalid agent: {agent}"})
                    return
                try:
                    results = run_probe(agent=agent)
                    self._json(200, {
                        "ok": True,
                        "results": results,
                    })
                except Exception as exc:
                    self._json(500, {"ok": False, "detail": str(exc)})
                return

            if parsed.path == "/root":
                raw_path = str(data.get("path") or "").strip()
                candidate = Path(raw_path)
                if not raw_path or not candidate.is_dir():
                    self._json(400, {"ok": False, "detail": "目錄不存在"})
                    return
                state.root = candidate.resolve()
                self._json(200, {"ok": True, "detail": str(state.root), "root": str(state.root)})
                return
            if parsed.path == "/agent-login":
                result = start_agent_login(str(data.get("id") or ""))
            elif parsed.path == "/agent-logout":
                result = start_agent_logout(str(data.get("id") or ""))
            elif parsed.path == "/run":
                result = run_workflow(root, str(data.get("workflow") or ""))
            elif parsed.path == "/continue":
                result = continue_run(
                    root,
                    str(data.get("workflow") or ""),
                    str(data.get("run_id") or ""),
                    re_resolve=bool(data.get("re_resolve")),
                )
            elif parsed.path == "/approve":
                result = approve_step(
                    root, str(data.get("run_id") or ""), str(data.get("step_id") or "")
                )
            elif parsed.path == "/cancel":
                rid = data.get("run_id")
                result = cancel_run(root, str(rid) if rid else None)
            else:
                self.send_response(404)
                self.end_headers()
                return
            self._json(200 if result.get("ok") else 400, result)

        def log_message(self, fmt: str, *a) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="ai-work repo root")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    root = args.root.resolve()

    handler_cls = make_handler(ServerState(root))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_cls)
    print(f"snapshot server on http://127.0.0.1:{args.port}/snapshot root={root}")
    server.serve_forever()


if __name__ == "__main__":
    main()
