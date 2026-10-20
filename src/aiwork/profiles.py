import json
from dataclasses import dataclass
from pathlib import Path

import yaml


class ProfileError(Exception):
    pass


@dataclass
class ResolvedProfile:
    env: dict[str, str]
    extra_args: list[str]
    mcp_config_path: Path | None
    skill_paths: list[Path]
    filtered_mcp: dict


def build_filtered_mcp_config(root: Path, profile_data: dict) -> dict:
    registry_path = root / "mcp-registry.yaml"
    registry_servers: list[dict] = []
    if registry_path.is_file():
        reg = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        registry_servers = list(reg.get("servers") or [])
    by_name = {s.get("name"): s for s in registry_servers if s.get("name")}
    servers: dict[str, dict] = {}
    for entry in profile_data.get("servers") or []:
        name = entry.get("name")
        if not name:
            continue
        base = dict(by_name.get(name) or {"name": name})
        if entry.get("allow_tools") is not None:
            base["allowTools"] = entry["allow_tools"]
        # Cursor-style mcpServers entry prefers command/args/url keys from registry
        servers[name] = base
    return {"mcpServers": servers}


def resolve_profile(
    *,
    root: Path,
    mcp_profile: str,
    skills: list[str],
    write_dir: Path | None = None,
) -> ResolvedProfile:
    profiles_dir = root / "mcp-profiles"
    path = profiles_dir / f"{mcp_profile}.yaml"
    if not path.is_file():
        raise ProfileError(f"unknown mcp_profile: {mcp_profile}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    skill_paths: list[Path] = []
    for name in skills:
        pack = root / "skills" / name
        if not pack.exists():
            raise ProfileError(f"unknown skill pack: {name}")
        skill_paths.append(pack)
    filtered = build_filtered_mcp_config(root, data)
    generated: Path | None = None
    if write_dir is not None:
        write_dir.mkdir(parents=True, exist_ok=True)
        generated = write_dir / "mcp.generated.json"
        generated.write_text(json.dumps(filtered, indent=2), encoding="utf-8")
    env = {
        "AIWORK_MCP_PROFILE": mcp_profile,
        "AIWORK_MCP_PROFILE_PATH": str(path),
    }
    if generated is not None:
        env["AIWORK_MCP_CONFIG"] = str(generated)
    if data.get("transport") == "gateway":
        url = data.get("url") or ""
        env["AIWORK_MCP_GATEWAY_URL"] = str(url)
        if data.get("gateway_profile"):
            env["AIWORK_MCP_GATEWAY_PROFILE"] = str(data["gateway_profile"])
    return ResolvedProfile(
        env=env,
        extra_args=[],
        mcp_config_path=generated or path,
        skill_paths=skill_paths,
        filtered_mcp=filtered,
    )


def validate_workflow_profiles(root: Path, workflow) -> None:
    for step in workflow.steps:
        resolve_profile(
            root=root, mcp_profile=step.mcp_profile, skills=[]
        )
