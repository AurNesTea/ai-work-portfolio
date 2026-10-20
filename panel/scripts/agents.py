"""Start each CLI's own login. No API-key or pay-as-you-go flags."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from pathlib import Path

# Subscription login only. Do not add --console or --with-api-key.
LOGIN_ARGV = {
    "cursor": ["agent", "login"],
    "claude": ["claude", "auth", "login"],
    "codex": ["codex", "login"],
    "gemini": ["agy"],
}
LOGOUT_ARGV = {
    "cursor": ["agent", "logout"],
    "claude": ["claude", "auth", "logout"],
    "codex": ["codex", "logout"],
}
STATUS_ARGV = {
    "cursor": ["agent", "status"],
    "claude": ["claude", "auth", "status"],
    "codex": ["codex", "login", "status"],
}
LABELS = {
    "cursor": "Cursor",
    "claude": "Claude",
    "codex": "Codex",
    "gemini": "Gemini",
}

_LOGGED_OUT_AGENTS: set[str] = set()
_STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "agent_status.json"


def _is_agent_logged_out(agent_id: str) -> bool:
    if not _LOGGED_OUT_AGENTS and _STATE_PATH.is_file():
        try:
            data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in data.items():
                    if v is False:
                        _LOGGED_OUT_AGENTS.add(k)
        except Exception:
            pass
    return agent_id in _LOGGED_OUT_AGENTS


def _set_agent_logged_out(agent_id: str, logged_out: bool) -> None:
    if logged_out:
        _LOGGED_OUT_AGENTS.add(agent_id)
    else:
        _LOGGED_OUT_AGENTS.discard(agent_id)
    if _STATE_PATH.parent.is_dir():
        try:
            _STATE_PATH.write_text(
                json.dumps({k: False for k in sorted(_LOGGED_OUT_AGENTS)}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass


def parse_claude_account(data: dict | None) -> str | None:
    if not isinstance(data, dict):
        return None
    if not data.get("loggedIn"):
        return None
    sub = data.get("subscriptionType")
    if not sub or not isinstance(sub, str) or not sub.strip():
        return None
    sub_clean = sub.strip()
    mapping = {
        "team": "Team",
        "pro": "Pro",
        "max": "Max",
    }
    plan = mapping.get(sub_clean.lower(), sub_clean)
    org = data.get("orgName")
    if isinstance(org, str) and org.strip():
        return f"{plan} · {org.strip()}"
    return plan


def parse_cursor_account(text: str | None) -> str | None:
    if not text or not isinstance(text, str):
        return None
    clean = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)
    lower = clean.lower()
    if "not logged in" in lower or "logged out" in lower:
        return None
    m = re.search(r"logged\s+in\s+as\s+(\S+)", clean, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def login_console_command(agent_id: str) -> list[str]:
    argv = LOGIN_ARGV[agent_id]
    if os.name == "nt":
        return ["cmd", "/c", "start", LABELS[agent_id], "cmd", "/k", *argv]
    return list(argv)


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = ["cmd", "/c", *argv] if os.name == "nt" else argv
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )


def _logged_in(agent_id: str, code: int, text: str) -> bool:
    lowered = text.lower()
    if agent_id == "claude":
        if re.search(r'"loggedin"\s*:\s*false', lowered):
            return False
        return code == 0
    # "Not logged in" contains "logged in"; a CLI that prints it with exit 0 is logged out.
    if "not logged in" in lowered or "logged out" in lowered:
        return False
    return code == 0 and "logged in" in lowered


def agent_rows() -> list[dict]:
    rows = []
    for agent_id, label in LABELS.items():
        program = LOGIN_ARGV[agent_id][0]
        if shutil.which(program) is None:
            rows.append(
                {"id": agent_id, "label": label, "state": "missing"}
            )
            continue
        status_argv = STATUS_ARGV.get(agent_id)
        if status_argv is None:
            if agent_id == "gemini":
                state = "logged_out" if _is_agent_logged_out("gemini") else "logged_in"
                rows.append({"id": agent_id, "label": label, "state": state})
            else:
                rows.append({"id": agent_id, "label": label, "state": "unknown"})
            continue
        try:
            proc = _run(status_argv)
        except (OSError, subprocess.TimeoutExpired):
            rows.append({"id": agent_id, "label": label, "state": "unknown"})
            continue
        text = f"{proc.stdout}\n{proc.stderr}"
        state = "logged_in" if _logged_in(agent_id, proc.returncode, text) else "logged_out"
        row: dict[str, str] = {"id": agent_id, "label": label, "state": state}
        if state == "logged_in":
            account_label = None
            if agent_id == "claude":
                try:
                    out = proc.stdout.strip()
                    if out:
                        try:
                            data = json.loads(out)
                        except json.JSONDecodeError:
                            start = out.find("{")
                            end = out.rfind("}")
                            if start != -1 and end != -1 and end > start:
                                data = json.loads(out[start : end + 1])
                            else:
                                data = None
                        if isinstance(data, dict):
                            account_label = parse_claude_account(data)
                except Exception:
                    account_label = None
            elif agent_id == "cursor":
                try:
                    account_label = parse_cursor_account(text)
                except Exception:
                    account_label = None
            if account_label:
                row["account_label"] = account_label
        rows.append(row)
    return rows


def start_agent_login(agent_id: str) -> dict:
    if agent_id not in LOGIN_ARGV:
        return {"ok": False, "detail": "unknown agent"}
    program = LOGIN_ARGV[agent_id][0]
    if shutil.which(program) is None:
        return {"ok": False, "detail": "找不到執行檔"}
    if agent_id == "gemini":
        _set_agent_logged_out("gemini", False)
        return {"ok": True, "detail": "Gemini 已登入就緒"}
    return {
        "ok": True,
        "detail": f"請在首頁終端內直接登入 {LABELS.get(agent_id, agent_id)}（已帶入選定專案目錄），不另開外顯視窗",
    }


def start_agent_logout(agent_id: str) -> dict:
    if agent_id not in LABELS:
        return {"ok": False, "detail": "unknown agent"}
    logout_argv = LOGOUT_ARGV.get(agent_id)
    if logout_argv:
        program = logout_argv[0]
        if shutil.which(program) is None:
            return {"ok": False, "detail": f"找不到執行檔 {program}"}
        try:
            proc = _run(logout_argv)
            text = f"{proc.stdout}\n{proc.stderr}".strip()
            ok = proc.returncode == 0 or "logged out" in text.lower() or "success" in text.lower()
            return {
                "ok": ok,
                "detail": f"{LABELS[agent_id]} 登出完成" if ok else f"{LABELS[agent_id]} 登出回應：{text}",
            }
        except Exception as exc:
            return {"ok": False, "detail": f"{LABELS[agent_id]} 登出失敗: {exc}"}
    elif agent_id == "gemini":
        _set_agent_logged_out("gemini", True)
        return {"ok": True, "detail": "Gemini 已登出"}
    return {"ok": False, "detail": "unknown agent"}
