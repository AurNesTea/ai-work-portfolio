from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import yaml
from pydantic import BaseModel, Field

from aiwork.models import AgentName, EffortName, StepSpec, WorkflowSpec
from aiwork.packs import find_role_definition, is_valid_role_path

VALID_AGENTS: frozenset[str] = frozenset({"cursor", "claude", "gemini"})
CLI_BY_AGENT: dict[str, str] = {
    "cursor": "agent",
    "claude": "claude",
    "gemini": "agy",
    "codex": "codex",
}
ROLE_ID_RE: re.Pattern = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MODEL_ID_RE: re.Pattern = re.compile(r"^[A-Za-z0-9._:-]+$")


class DispatchError(Exception):
    def __init__(self, message_or_errors: str | list[str]):
        if isinstance(message_or_errors, list):
            self.errors = list(message_or_errors)
            super().__init__("; ".join(self.errors))
        else:
            self.errors = [str(message_or_errors)]
            super().__init__(str(message_or_errors))


def aiwork_home() -> Path:
    return Path(os.environ.get("AIWORK_HOME", Path.home() / ".aiwork"))


def roles_config_path() -> Path:
    override = os.environ.get("AIWORK_ROLES")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "config" / "roles.yaml"


def models_config_path() -> Path:
    override = os.environ.get("AIWORK_MODELS")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "config" / "models.yaml"


def local_roles_path() -> Path:
    return aiwork_home() / "roles.local.yaml"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RoleRecord(BaseModel):
    agent: AgentName
    model: str
    effort: EffortName | None = None
    description: str
    source: Literal["shared", "local"] = "shared"


class TableMetadata(BaseModel):
    path: str
    sha256: str


class ResolvedStep(BaseModel):
    step_id: str
    role: str | None = None
    agent: AgentName
    model: str
    effort: EffortName = "medium"
    source: Literal["shared", "local", "explicit"]
    account: str | None = None
    role_file: str | None = None
    delivery: str | None = None


class ResolvedWorkflow(BaseModel):
    version: int = 1
    resolved_at: str
    tables: dict[str, TableMetadata]
    steps: dict[str, ResolvedStep]
    history: list[dict[str, Any]] = Field(default_factory=list)


def load_models_catalog(path: Path | None = None) -> tuple[dict[str, list[str]], Path, str]:
    target_path = path or models_config_path()
    if not target_path.is_file():
        raise DispatchError(f"models config file not found: {target_path} (set AIWORK_MODELS)")
    content = target_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(content)
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise DispatchError(f"invalid models.yaml: expected version: 1 at {target_path}")
    models_dict = raw.get("models")
    if not isinstance(models_dict, dict):
        raise DispatchError(f"invalid models.yaml: missing 'models' mapping at {target_path}")

    catalog: dict[str, list[str]] = {}
    for agent, entries in models_dict.items():
        if agent not in VALID_AGENTS:
            raise DispatchError(f"invalid agent '{agent}' in models.yaml (allowed: {sorted(VALID_AGENTS)})")
        if not isinstance(entries, list):
            raise DispatchError(f"models for '{agent}' must be a list in {target_path}")
        model_ids: list[str] = []
        for item in entries:
            if isinstance(item, str):
                mid = item
            elif isinstance(item, dict) and "id" in item:
                mid = str(item["id"])
            else:
                raise DispatchError(f"invalid model entry for '{agent}' in {target_path}: {item}")
            if not MODEL_ID_RE.match(mid):
                raise DispatchError(f"invalid model id '{mid}' for '{agent}' in {target_path}")
            model_ids.append(mid)
        catalog[agent] = model_ids

    return catalog, target_path, sha256_file(target_path)


def _parse_roles_dict(
    raw_roles: Any,
    source: Literal["shared", "local"],
    source_path: Path,
) -> dict[str, RoleRecord]:
    if not isinstance(raw_roles, dict):
        raise DispatchError(f"expected 'roles' mapping in {source_path}")
    allowed_keys = {"agent", "model", "effort", "description"}
    parsed: dict[str, RoleRecord] = {}

    for role_id, data in raw_roles.items():
        if not isinstance(role_id, str) or not ROLE_ID_RE.match(role_id):
            raise DispatchError(
                f"invalid role id '{role_id}' in {source_path}, must match ^[a-z][a-z0-9-]{{0,31}}$"
            )
        if not isinstance(data, dict):
            raise DispatchError(f"role '{role_id}' must be a mapping in {source_path}")

        for k in data.keys():
            if k not in allowed_keys:
                raise DispatchError(f"這個版本不認得欄位 {k} (role: {role_id} in {source_path})")

        agent_raw = data.get("agent")
        if not agent_raw:
            raise DispatchError(f"role '{role_id}' missing 'agent' in {source_path}")
        agent = "gemini" if agent_raw == "agy" else agent_raw

        if agent == "codex":
            raise DispatchError("codex 未啟用")
        if agent not in VALID_AGENTS:
            raise DispatchError(f"unknown agent '{agent}' in role '{role_id}' in {source_path}")

        model = data.get("model")
        if not model or not isinstance(model, str) or not MODEL_ID_RE.match(model):
            raise DispatchError(f"role '{role_id}' has invalid model '{model}' in {source_path}")

        desc = data.get("description")
        if not desc or not isinstance(desc, str) or not desc.strip():
            raise DispatchError(f"role '{role_id}' missing 'description' in {source_path}")

        effort = data.get("effort")
        if effort is not None and effort not in ("low", "medium", "high"):
            raise DispatchError(f"role '{role_id}' has invalid effort '{effort}' in {source_path}")

        parsed[role_id] = RoleRecord(
            agent=agent,
            model=model,
            effort=effort,
            description=desc.strip(),
            source=source,
        )

    return parsed


def load_roles(
    shared_path: Path | None = None,
    local_path: Path | None = None,
) -> tuple[dict[str, RoleRecord], dict[str, TableMetadata]]:
    s_path = shared_path or roles_config_path()
    l_path = local_path or local_roles_path()

    if not s_path.is_file():
        raise DispatchError(f"roles config file not found: {s_path} (set AIWORK_ROLES)")

    raw_shared = yaml.safe_load(s_path.read_text(encoding="utf-8"))
    if not isinstance(raw_shared, dict) or raw_shared.get("version") != 1:
        raise DispatchError(f"invalid roles.yaml: expected version: 1 at {s_path}")

    roles = _parse_roles_dict(raw_shared.get("roles", {}), "shared", s_path)
    tables_meta: dict[str, TableMetadata] = {
        "roles": TableMetadata(path=str(s_path), sha256=sha256_file(s_path))
    }

    if l_path.is_file():
        raw_local = yaml.safe_load(l_path.read_text(encoding="utf-8"))
        if not isinstance(raw_local, dict) or raw_local.get("version") != 1:
            raise DispatchError(f"invalid roles.local.yaml: expected version: 1 at {l_path}")
        local_roles = _parse_roles_dict(raw_local.get("roles", {}), "local", l_path)
        roles.update(local_roles)
        tables_meta["roles_local"] = TableMetadata(path=str(l_path), sha256=sha256_file(l_path))

    return roles, tables_meta


def resolve_workflow(
    spec: WorkflowSpec,
    *,
    roles: dict[str, RoleRecord] | None = None,
    models_catalog: dict[str, list[str]] | None = None,
    cli_checker: Callable[[str], bool] | None = None,
    tables_meta: dict[str, TableMetadata] | None = None,
    home: Path | None = None,
) -> ResolvedWorkflow:
    if roles is None or tables_meta is None:
        loaded_roles, loaded_meta = load_roles()
        if roles is None:
            roles = loaded_roles
        if tables_meta is None:
            tables_meta = loaded_meta

    if models_catalog is None:
        catalog, mpath, msha = load_models_catalog()
        tables_meta["models"] = TableMetadata(path=str(mpath), sha256=msha)
        models_catalog = catalog

    if cli_checker is None:
        cli_checker = lambda exe: bool(shutil.which(exe))

    errors: list[str] = []
    resolved_steps: dict[str, ResolvedStep] = {}

    for step in spec.steps:
        role_file: str | None = None
        delivery: str = "none"

        if step.role:
            if step.role not in roles:
                avail = ", ".join(sorted(roles.keys()))
                errors.append(f"step {step.id}: 未知 role '{step.role}'（可用 id: {avail}）")
                continue
            r_info = roles[step.role]
            agent = r_info.agent
            model = r_info.model
            source = r_info.source
            if "effort" in step.model_fields_set:
                effort = step.effort
            else:
                effort = r_info.effort or "medium"

            rf = find_role_definition(step.role, home=home)
            if rf is not None and rf.is_file():
                posix_str = rf.resolve().as_posix()
                role_file = posix_str
                if is_valid_role_path(posix_str):
                    delivery = "prompt-path"
                else:
                    delivery = "none"
                    warnings.warn(
                        f"Role definition path '{role_file}' contains invalid characters or whitespace; falling back to delivery: none",
                        UserWarning,
                        stacklevel=2,
                    )
            else:
                role_file = None
                delivery = "none"
        else:
            source = "explicit"
            agent = step.agent
            model = step.model
            effort = step.effort
            role_file = None
            delivery = "none"

            if agent == "codex":
                errors.append(f"step {step.id}: codex 未啟用")
                continue
            if agent not in VALID_AGENTS:
                errors.append(f"step {step.id}: 未知 agent '{agent}'")
                continue

        if agent in models_catalog:
            if model not in models_catalog[agent]:
                errors.append(f"step {step.id}: model '{model}' 不在 agent '{agent}' 的清單中")
        else:
            errors.append(f"step {step.id}: agent '{agent}' 沒有可用模型清單")

        cli_name = CLI_BY_AGENT.get(agent, agent)
        if not cli_checker(cli_name):
            errors.append(f"step {step.id}: CLI '{cli_name}' (agent: {agent}) 不在 PATH")

        resolved_steps[step.id] = ResolvedStep(
            step_id=step.id,
            role=step.role,
            agent=agent,
            model=model,
            effort=effort,
            source=source,
            role_file=role_file,
            delivery=delivery,
        )

    if errors:
        raise DispatchError(errors)

    return ResolvedWorkflow(
        version=1,
        resolved_at=datetime.now(timezone.utc).isoformat(),
        tables=tables_meta,
        steps=resolved_steps,
    )


def save_resolved(run_dir: Path, resolved: ResolvedWorkflow) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = run_dir / "resolved.json.tmp"
    final_path = run_dir / "resolved.json"
    payload = resolved.model_dump_json(indent=2)
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, final_path)
    return final_path


def load_resolved(run_dir: Path) -> ResolvedWorkflow:
    final_path = Path(run_dir) / "resolved.json"
    if not final_path.is_file():
        raise DispatchError(f"resolved.json not found in {run_dir}")
    content = final_path.read_text(encoding="utf-8")
    return ResolvedWorkflow.model_validate_json(content)


def re_resolve_run(
    workflow: WorkflowSpec,
    run_dir: Path,
    *,
    roles: dict[str, RoleRecord] | None = None,
    models_catalog: dict[str, list[str]] | None = None,
    cli_checker: Callable[[str], bool] | None = None,
    tables_meta: dict[str, TableMetadata] | None = None,
    home: Path | None = None,
) -> ResolvedWorkflow:
    existing = load_resolved(run_dir)
    if roles is None or tables_meta is None:
        loaded_roles, loaded_meta = load_roles()
        if roles is None:
            roles = loaded_roles
        if tables_meta is None:
            tables_meta = loaded_meta

    if models_catalog is None:
        catalog, mpath, msha = load_models_catalog()
        tables_meta["models"] = TableMetadata(path=str(mpath), sha256=msha)
        models_catalog = catalog

    if cli_checker is None:
        cli_checker = lambda exe: bool(shutil.which(exe))

    errors: list[str] = []
    new_steps: dict[str, ResolvedStep] = {}

    for step in workflow.steps:
        ok_marker = run_dir / "steps" / step.id / "ok"
        if ok_marker.is_file() and step.id in existing.steps:
            new_steps[step.id] = existing.steps[step.id]
            continue

        role_file: str | None = None
        delivery: str = "none"

        if step.role:
            if step.role not in roles:
                avail = ", ".join(sorted(roles.keys()))
                errors.append(f"step {step.id}: 未知 role '{step.role}'（可用 id: {avail}）")
                continue
            r_info = roles[step.role]
            agent = r_info.agent
            model = r_info.model
            source = r_info.source
            if "effort" in step.model_fields_set:
                effort = step.effort
            else:
                effort = r_info.effort or "medium"

            rf = find_role_definition(step.role, home=home)
            if rf is not None and rf.is_file():
                posix_str = rf.resolve().as_posix()
                role_file = posix_str
                if is_valid_role_path(posix_str):
                    delivery = "prompt-path"
                else:
                    delivery = "none"
                    warnings.warn(
                        f"Role definition path '{role_file}' contains invalid characters or whitespace; falling back to delivery: none",
                        UserWarning,
                        stacklevel=2,
                    )
            else:
                role_file = None
                delivery = "none"
        else:
            source = "explicit"
            agent = step.agent
            model = step.model
            effort = step.effort
            role_file = None
            delivery = "none"

            if agent == "codex":
                errors.append(f"step {step.id}: codex 未啟用")
                continue
            if agent not in VALID_AGENTS:
                errors.append(f"step {step.id}: 未知 agent '{agent}'")
                continue

        if agent in models_catalog:
            if model not in models_catalog[agent]:
                errors.append(f"step {step.id}: model '{model}' 不在 agent '{agent}' 的清單中")
        else:
            errors.append(f"step {step.id}: agent '{agent}' 沒有可用模型清單")

        cli_name = CLI_BY_AGENT.get(agent, agent)
        if not cli_checker(cli_name):
            errors.append(f"step {step.id}: CLI '{cli_name}' (agent: {agent}) 不在 PATH")

        new_steps[step.id] = ResolvedStep(
            step_id=step.id,
            role=step.role,
            agent=agent,
            model=model,
            effort=effort,
            source=source,
            role_file=role_file,
            delivery=delivery,
        )

    if errors:
        raise DispatchError(errors)

    history_entry = {
        "resolved_at": existing.resolved_at,
        "tables": {k: v.model_dump() for k, v in existing.tables.items()},
        "steps": {k: v.model_dump() for k, v in existing.steps.items()},
    }
    history = list(existing.history)
    history.append(history_entry)

    updated = ResolvedWorkflow(
        version=existing.version,
        resolved_at=datetime.now(timezone.utc).isoformat(),
        tables=tables_meta,
        steps=new_steps,
        history=history,
    )
    save_resolved(run_dir, updated)
    return updated


def validate_roles(
    roles: dict[str, RoleRecord] | None = None,
    models_catalog: dict[str, list[str]] | None = None,
    cli_checker: Callable[[str], bool] | None = None,
) -> tuple[list[str], list[str]]:
    if roles is None:
        roles, _ = load_roles()
    if models_catalog is None:
        models_catalog, _, _ = load_models_catalog()
    if cli_checker is None:
        cli_checker = lambda exe: bool(shutil.which(exe))

    errors: list[str] = []
    warnings: list[str] = []

    for role_id, record in roles.items():
        if record.agent == "codex":
            errors.append(f"role '{role_id}': codex 未啟用")
            continue
        if record.agent not in VALID_AGENTS:
            errors.append(f"role '{role_id}': 未知 agent '{record.agent}'")
            continue
        if record.agent not in models_catalog:
            errors.append(f"role '{role_id}': agent '{record.agent}' 沒有可用模型清單")
            continue
        if record.model not in models_catalog[record.agent]:
            errors.append(
                f"role '{role_id}': model '{record.model}' 不在 agent '{record.agent}' 的清單中"
            )

        cli_name = CLI_BY_AGENT.get(record.agent, record.agent)
        if not cli_checker(cli_name):
            warnings.append(f"CLI '{cli_name}' (agent: {record.agent}) 不在 PATH")

    return errors, warnings


def fetch_cli_models(agent: str) -> tuple[list[str] | None, str | None]:
    if agent == "claude":
        return None, "沒有列模型的指令"
    if agent == "cursor":
        cli = "agent"
        if shutil.which(cli) is None:
            return None, f"找不到執行檔 {cli}"
        cmd = ["cmd", "/c", cli, "--list-models"] if os.name == "nt" else [cli, "--list-models"]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, f"{cli} 執行逾時"
        except Exception as e:
            return None, f"{cli} 執行錯誤: {e}"

        if proc.returncode != 0:
            return None, f"{cli} 失敗 (結束碼 {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"

        models: list[str] = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or " - " not in line:
                continue
            mid = line.split(" - ")[0].strip()
            if MODEL_ID_RE.match(mid):
                models.append(mid)
        return models, None

    if agent == "gemini":
        cli = "agy"
        if shutil.which(cli) is None:
            return None, f"找不到執行檔 {cli}"
        cmd = ["cmd", "/c", cli, "models"] if os.name == "nt" else [cli, "models"]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, f"{cli} 執行逾時"
        except Exception as e:
            return None, f"{cli} 執行錯誤: {e}"

        if proc.returncode != 0:
            return None, f"{cli} 失敗 (結束碼 {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"

        models = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("Fetching") or line.startswith("Available"):
                continue
            parts = re.split(r"\t+|\s{2,}", line)
            if parts:
                mid = parts[0].strip()
                if MODEL_ID_RE.match(mid):
                    models.append(mid)
        return models, None

    return None, f"未知 agent '{agent}'"


def check_models_catalog(catalog: dict[str, list[str]] | None = None) -> dict[str, dict[str, Any]]:
    if catalog is None:
        catalog, _, _ = load_models_catalog()

    result: dict[str, dict[str, Any]] = {}
    for agent in sorted(VALID_AGENTS):
        catalog_models = set(catalog.get(agent, []))
        live_models, notice = fetch_cli_models(agent)
        if live_models is not None:
            live_set = set(live_models)
            extra_in_cli = sorted(live_set - catalog_models)
            missing_in_cli = sorted(catalog_models - live_set)
            result[agent] = {
                "status": "ok",
                "extra_in_cli": extra_in_cli,
                "missing_in_cli": missing_in_cli,
                "total_cli": len(live_set),
                "total_catalog": len(catalog_models),
            }
        else:
            result[agent] = {
                "status": "notice" if notice == "沒有列模型的指令" else "error",
                "message": notice,
                "total_catalog": len(catalog_models),
            }
    return result


