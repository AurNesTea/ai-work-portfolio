"""Role definitions and skill pool scanning module (Phase 2 P2-3).

Re-exports core role definition and scanning symbols from aiwork.packs.
"""

from __future__ import annotations

from aiwork.packs import (
    RoleDef,
    SAFE_ROLE_PATH_RE,
    check_role_skills,
    deserialize_role_def,
    dump_role_def,
    find_role_definition,
    get_missing_skills,
    get_role_delivery_status,
    is_valid_role_path,
    load_role_def,
    parse_role_def,
    save_role_def,
    scan_skills_pool,
    serialize_role_def,
    build_role_prompt,
    inject_role_header,
)

__all__ = [
    "RoleDef",
    "SAFE_ROLE_PATH_RE",
    "build_role_prompt",
    "check_role_skills",
    "deserialize_role_def",
    "dump_role_def",
    "find_role_definition",
    "get_missing_skills",
    "get_role_delivery_status",
    "inject_role_header",
    "is_valid_role_path",
    "load_role_def",
    "parse_role_def",
    "save_role_def",
    "scan_skills_pool",
    "serialize_role_def",
]
