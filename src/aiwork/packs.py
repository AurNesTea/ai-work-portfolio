from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Literal

import yaml
from pydantic import BaseModel, Field

# Constants & Patterns
PACK_ID_RE: re.Pattern = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ROLE_ID_RE: re.Pattern = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
ITEM_NAME_RE: re.Pattern = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

FRONTMATTER_PATTERN: re.Pattern = re.compile(
    r"^---\r?\n(.*?)\r?\n---(?:\r?\n(.*))?$",
    re.DOTALL,
)

MAX_TOTAL_UNCOMPRESSED_SIZE: int = 20 * 1024 * 1024  # 20 MB
MAX_FILE_COUNT: int = 300
MAX_SINGLE_FILE_SIZE: int = 1 * 1024 * 1024  # 1 MB
MAX_RULE_FILE_SIZE: int = 64 * 1024  # 64 KB

ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".md", ".mdc", ".yaml", ".yml", ".json", ".txt"}
)
SKILL_SCRIPT_EXTENSIONS: frozenset[str] = frozenset(
    {".py", ".sh", ".ps1", ".js", ".ts"}
)
FORBIDDEN_EXTENSIONS: frozenset[str] = frozenset(
    {".exe", ".dll", ".bat", ".cmd", ".com", ".msi", ".lnk", ".scr", ".jar"}
)

WINDOWS_RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)


class PackError(Exception):
    """Base exception for all pack-related errors."""


class PackValidationError(PackError):
    """Raised when a pack fails validation."""

    def __init__(self, message_or_errors: str | list[str]):
        if isinstance(message_or_errors, list):
            self.errors = list(message_or_errors)
            super().__init__("; ".join(self.errors))
        else:
            self.errors = [str(message_or_errors)]
            super().__init__(str(message_or_errors))


class PackSecurityError(PackError):
    """Raised when an operation encounters malicious or out-of-bounds input."""


def aiwork_home(home: Path | None = None) -> Path:
    if home is not None:
        return Path(home)
    return Path(os.environ.get("AIWORK_HOME", Path.home() / ".aiwork"))


def user_home(home: Path | None = None) -> Path:
    if home is not None:
        return Path(home)
    if "AIWORK_USER_HOME" in os.environ:
        return Path(os.environ["AIWORK_USER_HOME"])
    return Path.home()


def applied_manifest_path(home: Path | None = None) -> Path:
    return (home or aiwork_home()) / "applied.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_frontmatter(content: str) -> tuple[dict[str, Any] | None, str]:
    """Parse YAML frontmatter from markdown text.

    Returns (metadata_dict, body_text). If no frontmatter is found, metadata_dict is None.
    """
    if not content.startswith("---"):
        return None, content

    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return None, content

    fm_raw = match.group(1)
    body = match.group(2) or ""

    try:
        metadata = yaml.safe_load(fm_raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(metadata, dict):
        raise ValueError("Frontmatter must be a YAML mapping")

    return metadata, body


class PackItem(BaseModel):
    kind: Literal["agent", "rule", "skill"]
    name: str
    path: str
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    has_scripts: bool = False
    sha256: str = ""


class Pack(BaseModel):
    id: str
    name: str
    description: str
    version: int | str = 1
    items: list[PackItem] = Field(default_factory=list)
    has_scripts: bool = False
    path: Path | None = None

    def get_item(self, kind: str, name: str) -> PackItem | None:
        for item in self.items:
            if item.kind == kind and item.name == name:
                return item
        return None


class ManifestEntry(BaseModel):
    target_path: str
    sha256: str
    source_pack: str
    item: str
    mode: Literal["file", "link", "copy"]
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    backup_path: str | None = None


def normalize_target_path(path: str | Path) -> str:
    resolved = Path(path).resolve().as_posix()
    if os.name == "nt":
        return resolved.lower()
    return resolved


class Manifest(BaseModel):
    version: int = 1
    entries: list[ManifestEntry] = Field(default_factory=list)

    def get(self, target_path: str | Path) -> ManifestEntry | None:
        target_norm = normalize_target_path(target_path)
        for entry in self.entries:
            if normalize_target_path(entry.target_path) == target_norm:
                return entry
        return None

    def add(self, entry: ManifestEntry) -> None:
        target_norm = normalize_target_path(entry.target_path)
        for i, existing in enumerate(self.entries):
            if normalize_target_path(existing.target_path) == target_norm:
                self.entries[i] = entry
                return
        self.entries.append(entry)

    def remove(self, target_path: str | Path) -> ManifestEntry | None:
        target_norm = normalize_target_path(target_path)
        for i, existing in enumerate(self.entries):
            if normalize_target_path(existing.target_path) == target_norm:
                return self.entries.pop(i)
        return None

    def find_by_pack(self, source_pack: str) -> list[ManifestEntry]:
        return [e for e in self.entries if e.source_pack == source_pack]

    def save(self, path: Path | None = None, home: Path | None = None) -> Path:
        target_file = path if path is not None else applied_manifest_path(home)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = target_file.parent / f"{target_file.name}.{os.getpid()}.tmp"
        content = self.model_dump_json(indent=2)
        tmp_file.write_text(content, encoding="utf-8")
        os.replace(tmp_file, target_file)
        return target_file

    @classmethod
    def load(cls, path: Path | None = None, home: Path | None = None) -> Manifest:
        target_file = path if path is not None else applied_manifest_path(home)
        if not target_file.exists():
            return cls(version=1, entries=[])
        content = target_file.read_text(encoding="utf-8")
        return cls.model_validate_json(content)


def load_manifest(path: Path | None = None, home: Path | None = None) -> Manifest:
    return Manifest.load(path, home=home)


def save_manifest(manifest: Manifest, path: Path | None = None, home: Path | None = None) -> Path:
    return manifest.save(path, home=home)


class ExtractResult(list):
    """Result of safe_extract_zip containing extracted paths and script flag."""

    def __init__(self, extracted_files: list[Path], has_scripts: bool = False):
        super().__init__(extracted_files)
        self.files = extracted_files
        self.has_scripts = has_scripts


def _ensure_dir(dest_dir: Path, root: Path, created: list[Path]) -> None:
    parts_to_create: list[Path] = []
    curr = dest_dir
    while curr != root and curr.is_relative_to(root):
        if not curr.exists():
            parts_to_create.append(curr)
        curr = curr.parent
    for p in reversed(parts_to_create):
        p.mkdir(exist_ok=True)
        created.append(p)


def safe_extract_zip(
    zip_bytes_or_file: bytes | bytearray | str | Path | BinaryIO,
    target_dir: Path | str,
) -> ExtractResult:
    """Safely extracts a pack zip archive with strict bounds, path, and content checks.

    Rejects directory traversal (..), absolute paths, NTFS streams (:),
    Windows reserved names, symlinks, duplicate case collisions, size limits,
    unauthorized extensions, and non-UTF-8 text files.
    Cleans up any partially extracted files on failure.
    """
    target_path = Path(target_dir).resolve()
    target_path.mkdir(parents=True, exist_ok=True)

    if isinstance(zip_bytes_or_file, (bytes, bytearray)):
        file_obj: BinaryIO | io.BytesIO = io.BytesIO(zip_bytes_or_file)
    elif isinstance(zip_bytes_or_file, (str, Path)):
        p = Path(zip_bytes_or_file)
        if not p.is_file():
            raise PackSecurityError(f"Zip file not found: {p}")
        file_obj = io.BytesIO(p.read_bytes())
    else:
        file_obj = zip_bytes_or_file

    try:
        zf = zipfile.ZipFile(file_obj, "r")
    except Exception as exc:
        raise PackSecurityError(f"Corrupted or invalid zip archive: {exc}") from exc

    infolist = zf.infolist()

    # 1. Check file count
    if len(infolist) > MAX_FILE_COUNT:
        raise PackSecurityError(
            f"Zip entry count {len(infolist)} exceeds limit of {MAX_FILE_COUNT}"
        )

    # 2. Check total uncompressed size and single file size in metadata
    total_declared_size = sum(info.file_size for info in infolist)
    if total_declared_size > MAX_TOTAL_UNCOMPRESSED_SIZE:
        raise PackSecurityError(
            f"Zip declared total size {total_declared_size} exceeds limit of {MAX_TOTAL_UNCOMPRESSED_SIZE}"
        )

    for info in infolist:
        if info.file_size > MAX_SINGLE_FILE_SIZE:
            raise PackSecurityError(
                f"File '{info.filename}' size {info.file_size} exceeds single file limit of {MAX_SINGLE_FILE_SIZE}"
            )

    # 3. Pre-validate all member paths, names, symlinks, and extensions
    seen_lower_paths: set[str] = set()
    has_scripts = False

    for info in infolist:
        raw_name = info.filename

        # Reject NTFS alternative data streams and drive letters
        if ":" in raw_name:
            raise PackSecurityError(f"Illegal character ':' in path: '{raw_name}'")

        # Reject symlinks / reparse points
        is_symlink = (
            info.create_system == 3
            and (info.external_attr >> 16) & 0o170000 == 0o120000
        ) or bool(info.external_attr & 0x400)
        if is_symlink:
            raise PackSecurityError(f"Symlinks and reparse points are forbidden: '{raw_name}'")

        norm_path = raw_name.replace("\\", "/")
        if norm_path.startswith("/") or norm_path.startswith("\\"):
            raise PackSecurityError(f"Absolute paths are forbidden: '{raw_name}'")

        parts = [p for p in norm_path.split("/") if p]
        if not parts:
            continue

        if any(p == ".." for p in parts):
            raise PackSecurityError(f"Directory traversal '..' is forbidden: '{raw_name}'")

        # Check Windows reserved names
        for part in parts:
            base = part.split(".")[0].upper()
            if base in WINDOWS_RESERVED_NAMES:
                raise PackSecurityError(
                    f"Windows reserved device name '{part}' is forbidden: '{raw_name}'"
                )

        # Check duplicate case collisions
        lower_path = "/".join(parts).lower()
        if lower_path in seen_lower_paths:
            raise PackSecurityError(
                f"Duplicate/case-collision path detected: '{raw_name}'"
            )
        seen_lower_paths.add(lower_path)

        # Extension check for files
        is_dir = info.is_dir() or raw_name.endswith("/")
        if not is_dir:
            file_name = parts[-1]
            suffix = Path(file_name).suffix.lower()

            if suffix in FORBIDDEN_EXTENSIONS:
                raise PackSecurityError(
                    f"Forbidden file extension '{suffix}': '{raw_name}'"
                )

            # Check if within skills directory
            in_skills = "skills" in parts and parts.index("skills") < len(parts) - 1
            if in_skills:
                if suffix not in (ALLOWED_EXTENSIONS | SKILL_SCRIPT_EXTENSIONS):
                    raise PackSecurityError(
                        f"Extension '{suffix}' is not allowed in skill directory: '{raw_name}'"
                    )
                if suffix in SKILL_SCRIPT_EXTENSIONS:
                    has_scripts = True
            else:
                if suffix in SKILL_SCRIPT_EXTENSIONS:
                    raise PackSecurityError(
                        f"Script extension '{suffix}' is only allowed inside skills directory: '{raw_name}'"
                    )
                if suffix not in ALLOWED_EXTENSIONS:
                    raise PackSecurityError(
                        f"Extension '{suffix}' is not allowed: '{raw_name}'"
                    )

        # Resolve destination path
        dest = (target_path / Path(*parts)).resolve()
        if not dest.is_relative_to(target_path):
            raise PackSecurityError(
                f"Resolved path '{dest}' escapes target directory '{target_path}'"
            )

    # 4. Perform extraction with cumulative size, single file, and UTF-8 verification
    created_paths: list[Path] = []
    extracted_files: list[Path] = []
    cumulative_size = 0

    try:
        for info in infolist:
            parts = [p for p in info.filename.replace("\\", "/").split("/") if p]
            if not parts:
                continue

            dest = (target_path / Path(*parts)).resolve()
            is_dir = info.is_dir() or info.filename.endswith("/")

            if is_dir:
                _ensure_dir(dest, target_path, created_paths)
                continue

            _ensure_dir(dest.parent, target_path, created_paths)

            with zf.open(info) as src:
                content = src.read()

            cumulative_size += len(content)
            if len(content) > MAX_SINGLE_FILE_SIZE:
                raise PackSecurityError(
                    f"File '{info.filename}' uncompressed size {len(content)} exceeds limit of {MAX_SINGLE_FILE_SIZE}"
                )
            if cumulative_size > MAX_TOTAL_UNCOMPRESSED_SIZE:
                raise PackSecurityError(
                    f"Total uncompressed size {cumulative_size} exceeds limit of {MAX_TOTAL_UNCOMPRESSED_SIZE}"
                )

            # Check UTF-8 validity
            try:
                content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PackSecurityError(
                    f"File '{info.filename}' contains non-UTF-8 bytes: {exc}"
                ) from exc

            dest.write_bytes(content)
            created_paths.append(dest)
            extracted_files.append(dest)

    except Exception:
        # Clean up any created files/directories on failure
        for p in reversed(created_paths):
            if p.is_file():
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            elif p.is_dir():
                try:
                    p.rmdir()
                except OSError:
                    pass
        raise

    return ExtractResult(extracted_files, has_scripts=has_scripts)



def validate_pack(pack_dir: Path | str) -> Pack:
    """Validates a pack directory structure, item metadata, and constraints.

    Returns the validated Pack instance.
    Raises PackValidationError if any check fails.
    """
    path = Path(pack_dir).resolve()
    errors: list[str] = []

    if not path.exists():
        raise PackValidationError(f"Pack directory does not exist: {path}")
    if not path.is_dir():
        raise PackValidationError(f"Pack path is not a directory: {path}")

    pack_yaml_path = path / "pack.yaml"
    if not pack_yaml_path.is_file():
        pack_yaml_path = path / "pack.yml"
    if not pack_yaml_path.is_file():
        raise PackValidationError(f"Missing pack.yaml in pack directory: {path}")

    # 1. Parse and validate pack.yaml
    try:
        pack_meta_content = pack_yaml_path.read_text(encoding="utf-8")
        pack_meta = yaml.safe_load(pack_meta_content)
    except UnicodeDecodeError as exc:
        raise PackValidationError(f"pack.yaml is not valid UTF-8: {exc}") from exc
    except yaml.YAMLError as exc:
        raise PackValidationError(f"Failed to parse pack.yaml: {exc}") from exc

    if not isinstance(pack_meta, dict):
        raise PackValidationError("pack.yaml must be a YAML mapping")

    pack_id = pack_meta.get("id")
    pack_name = pack_meta.get("name")
    pack_desc = pack_meta.get("description")
    pack_version = pack_meta.get("version", 1)

    if not pack_id or not isinstance(pack_id, str):
        errors.append("pack.yaml missing or invalid 'id'")
    elif not PACK_ID_RE.match(pack_id):
        errors.append(
            f"Invalid pack id '{pack_id}', must match ^[a-z0-9][a-z0-9._-]{{0,63}}$"
        )

    if not pack_name or not isinstance(pack_name, str):
        errors.append("pack.yaml missing or invalid 'name'")
    elif not ITEM_NAME_RE.match(pack_name):
        errors.append(
            f"Invalid pack name '{pack_name}', must match ^[a-z0-9][a-z0-9._-]{{0,63}}$"
        )

    if not pack_desc or not isinstance(pack_desc, str) or not pack_desc.strip():
        errors.append("pack.yaml missing or empty 'description'")

    items: list[PackItem] = []
    seen_rules: set[str] = set()

    # 2. Check agents/
    agents_dir = path / "agents"
    if agents_dir.exists():
        if not agents_dir.is_dir():
            errors.append("'agents' must be a directory")
        else:
            for entry in sorted(agents_dir.iterdir()):
                if entry.is_dir():
                    errors.append(f"Subdirectories not allowed in agents/: '{entry.name}'")
                    continue
                if entry.suffix.lower() != ".md":
                    errors.append(f"Non-markdown file in agents/: '{entry.name}'")
                    continue

                role_id = entry.stem
                if not ROLE_ID_RE.match(role_id):
                    errors.append(
                        f"Invalid role id '{role_id}' in agents/{entry.name}, must match ^[a-z][a-z0-9-]{{0,31}}$"
                    )

                try:
                    agent_text = entry.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    errors.append(f"agents/{entry.name} is not valid UTF-8: {exc}")
                    continue

                try:
                    fm, _ = parse_frontmatter(agent_text)
                except ValueError as exc:
                    errors.append(f"agents/{entry.name} frontmatter error: {exc}")
                    continue

                if fm is None:
                    errors.append(f"agents/{entry.name} missing frontmatter")
                    continue

                fm_name = fm.get("name")
                if fm_name != role_id:
                    errors.append(
                        f"agents/{entry.name} frontmatter 'name' ('{fm_name}') must equal filename stem ('{role_id}')"
                    )

                fm_desc = fm.get("description")
                if not fm_desc or not isinstance(fm_desc, str) or not fm_desc.strip():
                    errors.append(f"agents/{entry.name} missing or empty 'description'")

                fm_skills = fm.get("skills")
                valid_skills: list[str] = []
                if fm_skills is not None:
                    if not isinstance(fm_skills, list) or not all(
                        isinstance(s, str) for s in fm_skills
                    ):
                        errors.append(
                            f"agents/{entry.name} 'skills' must be a list of strings"
                        )
                    else:
                        valid_skills = list(fm_skills)

                items.append(
                    PackItem(
                        kind="agent",
                        name=role_id,
                        path=f"agents/{entry.name}",
                        description=str(fm_desc or ""),
                        skills=valid_skills,
                        has_scripts=False,
                        sha256=sha256_file(entry),
                    )
                )

    # 3. Check rules/
    rules_dir = path / "rules"
    if rules_dir.exists():
        if not rules_dir.is_dir():
            errors.append("'rules' must be a directory")
        else:
            for entry in sorted(rules_dir.iterdir()):
                if entry.is_dir():
                    errors.append(f"Subdirectories not allowed in rules/: '{entry.name}'")
                    continue
                if entry.suffix.lower() not in (".md", ".mdc"):
                    errors.append(
                        f"Rule file must have .md or .mdc extension: '{entry.name}'"
                    )
                    continue

                rule_name = entry.stem
                if not ITEM_NAME_RE.match(rule_name):
                    errors.append(
                        f"Invalid rule name '{rule_name}' in rules/{entry.name}, must match ^[a-z0-9][a-z0-9._-]{{0,63}}$"
                    )

                if rule_name in seen_rules:
                    errors.append(
                        f"Duplicate rule stem '{rule_name}' in rules directory"
                    )
                seen_rules.add(rule_name)

                if entry.stat().st_size > MAX_RULE_FILE_SIZE:
                    errors.append(
                        f"rules/{entry.name} size {entry.stat().st_size} exceeds 64 KB limit"
                    )

                try:
                    rule_text = entry.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    errors.append(f"rules/{entry.name} is not valid UTF-8: {exc}")
                    continue

                desc = ""
                if rule_text.startswith("---"):
                    try:
                        fm, _ = parse_frontmatter(rule_text)
                        if fm and isinstance(fm.get("description"), str):
                            desc = fm["description"]
                    except ValueError as exc:
                        errors.append(f"rules/{entry.name} invalid frontmatter: {exc}")

                items.append(
                    PackItem(
                        kind="rule",
                        name=rule_name,
                        path=f"rules/{entry.name}",
                        description=desc,
                        skills=[],
                        has_scripts=False,
                        sha256=sha256_file(entry),
                    )
                )

    # 4. Check skills/
    skills_dir = path / "skills"
    if skills_dir.exists():
        if not skills_dir.is_dir():
            errors.append("'skills' must be a directory")
        else:
            for skill_entry in sorted(skills_dir.iterdir()):
                if not skill_entry.is_dir():
                    errors.append(
                        f"Direct files not allowed in skills/: '{skill_entry.name}'"
                    )
                    continue

                skill_name = skill_entry.name
                if not ITEM_NAME_RE.match(skill_name):
                    errors.append(
                        f"Invalid skill name '{skill_name}', must match ^[a-z0-9][a-z0-9._-]{{0,63}}$"
                    )

                skill_md_path = skill_entry / "SKILL.md"
                if not skill_md_path.is_file():
                    errors.append(
                        f"Missing SKILL.md in skill directory: skills/{skill_name}"
                    )
                    continue

                try:
                    skill_text = skill_md_path.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    errors.append(
                        f"skills/{skill_name}/SKILL.md is not valid UTF-8: {exc}"
                    )
                    continue

                try:
                    fm, _ = parse_frontmatter(skill_text)
                except ValueError as exc:
                    errors.append(
                        f"skills/{skill_name}/SKILL.md frontmatter error: {exc}"
                    )
                    continue

                if fm is None:
                    errors.append(
                        f"skills/{skill_name}/SKILL.md missing frontmatter"
                    )
                    continue

                fm_name = fm.get("name")
                if fm_name != skill_name:
                    errors.append(
                        f"skills/{skill_name}/SKILL.md frontmatter 'name' ('{fm_name}') must equal folder name ('{skill_name}')"
                    )

                fm_desc = fm.get("description")
                if not fm_desc or not isinstance(fm_desc, str) or not fm_desc.strip():
                    errors.append(
                        f"skills/{skill_name}/SKILL.md missing or empty 'description'"
                    )

                # Scan all files in the skill directory
                skill_has_scripts = False
                for file_path in sorted(skill_entry.rglob("*")):
                    if file_path.is_dir():
                        continue

                    suffix = file_path.suffix.lower()
                    rel_file = file_path.relative_to(path).as_posix()

                    if suffix in FORBIDDEN_EXTENSIONS:
                        errors.append(
                            f"Forbidden file extension in skill: '{rel_file}'"
                        )
                        continue

                    if suffix not in (ALLOWED_EXTENSIONS | SKILL_SCRIPT_EXTENSIONS):
                        errors.append(
                            f"Extension '{suffix}' not allowed in skill: '{rel_file}'"
                        )
                        continue

                    if suffix in SKILL_SCRIPT_EXTENSIONS:
                        skill_has_scripts = True

                    try:
                        file_path.read_text(encoding="utf-8")
                    except UnicodeDecodeError as exc:
                        errors.append(f"Skill file is not valid UTF-8 '{rel_file}': {exc}")

                items.append(
                    PackItem(
                        kind="skill",
                        name=skill_name,
                        path=f"skills/{skill_name}/SKILL.md",
                        description=str(fm_desc or ""),
                        skills=[],
                        has_scripts=skill_has_scripts,
                        sha256=sha256_file(skill_md_path),
                    )
                )

    # 5. Check unexpected top-level files / directories
    known_top_levels = {"pack.yaml", "pack.yml", "agents", "rules", "skills"}
    for entry in path.iterdir():
        if entry.name not in known_top_levels:
            if entry.is_dir():
                errors.append(f"Unexpected top-level directory: '{entry.name}'")
            else:
                suffix = entry.suffix.lower()
                if suffix not in ALLOWED_EXTENSIONS or suffix in FORBIDDEN_EXTENSIONS:
                    errors.append(f"Unexpected top-level file: '{entry.name}'")

    if errors:
        raise PackValidationError(errors)

    has_any_scripts = any(item.has_scripts for item in items)

    return Pack(
        id=str(pack_id),
        name=str(pack_name),
        description=str(pack_desc),
        version=pack_version,
        items=items,
        has_scripts=has_any_scripts,
        path=path,
    )


# =====================================================================
# Machine Profile & CLI Directory Detection
# =====================================================================


def detect_cli_dirs(home: Path | None = None) -> dict[str, str]:
    base = home or user_home()
    return {
        "agents": str(base / ".agents"),
        "claude": str(base / ".claude"),
        "cursor": str(base / ".cursor"),
        "gemini": str(base / ".gemini" / "config"),
    }


def machine_profile_path(home: Path | None = None) -> Path:
    return (home or aiwork_home()) / "machine.yaml"


class MachineProfile(BaseModel):
    name: str = Field(
        default_factory=lambda: os.environ.get("COMPUTERNAME") or socket.gethostname()
    )
    libraries: list[str] = Field(
        default_factory=lambda: [str(aiwork_home() / "library")]
    )
    enabled_packs: list[str] = Field(default_factory=list)
    scope: Literal["global"] = "global"
    cli_dirs: dict[str, str] = Field(default_factory=dict)


def load_machine_profile(
    path: Path | None = None, home: Path | None = None
) -> MachineProfile:
    target = Path(path) if path is not None else machine_profile_path(home)
    detected_cli = detect_cli_dirs(home)
    if not target.exists():
        return MachineProfile(cli_dirs=detected_cli)
    try:
        content = target.read_text(encoding="utf-8")
        data = yaml.safe_load(content) or {}
    except Exception as exc:
        raise PackError(f"Failed to load machine profile {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise PackError(f"Machine profile must be a YAML mapping in {target}")
    cli_dirs = data.get("cli_dirs") or {}
    for k, v in detected_cli.items():
        if k not in cli_dirs:
            cli_dirs[k] = v
    data["cli_dirs"] = cli_dirs
    return MachineProfile.model_validate(data)


def save_machine_profile(
    profile: MachineProfile, path: Path | None = None, home: Path | None = None
) -> Path:
    target = Path(path) if path is not None else machine_profile_path(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = target.parent / f"{target.name}.{os.getpid()}.tmp"
    data = profile.model_dump()
    content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    tmp_file.write_text(content, encoding="utf-8")
    os.replace(tmp_file, target)
    return target


def enable_pack(
    pack_id: str, profile_path: Path | None = None, home: Path | None = None
) -> MachineProfile:
    profile = load_machine_profile(path=profile_path, home=home)
    if pack_id not in profile.enabled_packs:
        profile.enabled_packs.append(pack_id)
        save_machine_profile(profile, path=profile_path, home=home)
    return profile


def disable_pack(
    pack_id: str, profile_path: Path | None = None, home: Path | None = None
) -> MachineProfile:
    profile = load_machine_profile(path=profile_path, home=home)
    if pack_id in profile.enabled_packs:
        profile.enabled_packs.remove(pack_id)
        save_machine_profile(profile, path=profile_path, home=home)
    return profile


def find_pack(
    pack_id: str,
    libraries: list[str | Path] | None = None,
    home: Path | None = None,
) -> Pack | None:
    if libraries is None:
        profile = load_machine_profile(home=home)
        libraries = [Path(lib) for lib in profile.libraries]
    for lib in libraries:
        lib_path = Path(lib).expanduser().resolve()
        if not lib_path.is_dir():
            continue
        candidate = lib_path / pack_id
        if candidate.is_dir():
            try:
                return validate_pack(candidate)
            except Exception:
                pass
        for sub in sorted(lib_path.iterdir()):
            if sub.is_dir():
                try:
                    p = validate_pack(sub)
                    if p.id == pack_id:
                        return p
                except Exception:
                    pass
    return None


def list_packs(
    libraries: list[str | Path] | None = None,
    home: Path | None = None,
) -> list[Pack]:
    if libraries is None:
        profile = load_machine_profile(home=home)
        libraries = [Path(lib) for lib in profile.libraries]
    packs: list[Pack] = []
    seen_ids: set[str] = set()
    for lib in libraries:
        lib_path = Path(lib).expanduser().resolve()
        if not lib_path.is_dir():
            continue
        for sub in sorted(lib_path.iterdir()):
            if sub.is_dir():
                try:
                    p = validate_pack(sub)
                    if p.id not in seen_ids:
                        seen_ids.add(p.id)
                        packs.append(p)
                except Exception:
                    pass
    return packs


# =====================================================================
# Apply & Undo Core
# =====================================================================


class ApplyResult(BaseModel):
    plans: dict[str, list[Any]] = Field(
        default_factory=lambda: {
            "add": [],
            "replace": [],
            "conflicts": [],
            "dirs_to_create": [],
        }
    )
    success: bool = True
    dry_run: bool = True
    applied_entries: list[ManifestEntry] = Field(default_factory=list)
    backup_dir: str | None = None
    errors: list[str] = Field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        if item == "plans":
            return self.plans
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)


class UndoResult(BaseModel):
    removed: list[str] = Field(default_factory=list)
    restored: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)


def _resolve_target_actions(
    pack: Pack,
    profile: MachineProfile,
    home: Path | None = None,
) -> list[tuple[Path, Path, Literal["file", "link", "copy"], str, str]]:
    """Resolves (target_path, source_path, mode, item_name, item_kind) actions for a pack.

    Applies directory deduplication when CLI directories resolve to the same realpath.
    """
    actions: list[tuple[Path, Path, Literal["file", "link", "copy"], str, str]] = []
    if not pack.path:
        raise PackError(f"Pack '{pack.id}' has no directory path")

    pack_dir = pack.path
    base_home = home or user_home()
    agents_base = Path(profile.cli_dirs.get("agents", base_home / ".agents"))

    for item in pack.items:
        if item.kind == "agent":
            source_file = pack_dir / item.path
            primary_agents_dir = agents_base / "agents"
            primary_target = primary_agents_dir / f"{item.name}.md"
            actions.append((primary_target, source_file, "file", item.name, "agent"))

            # Deduplication for other CLIs
            for cli_key in ("claude", "cursor"):
                if cli_key in profile.cli_dirs:
                    cli_agents_dir = Path(profile.cli_dirs[cli_key]) / "agents"
                    if cli_agents_dir.resolve() == primary_agents_dir.resolve():
                        continue
                    actions.append((cli_agents_dir / f"{item.name}.md", source_file, "file", item.name, "agent"))

        elif item.kind == "rule":
            source_file = pack_dir / item.path
            primary_rules_dir = agents_base / "rules"
            target_mdc = primary_rules_dir / f"{item.name}.mdc"
            target_md = primary_rules_dir / f"{item.name}.md"

            gemini_base = Path(profile.cli_dirs.get("gemini", base_home / ".gemini" / "config"))
            target_gemini_md = gemini_base / ".agents" / "rules" / f"{item.name}.md"

            actions.append((target_mdc, source_file, "file", f"{item.name}.mdc", "rule"))
            actions.append((target_md, target_mdc, "link", f"{item.name}.md", "rule"))
            actions.append((target_gemini_md, target_mdc, "link", f"{item.name}.md", "rule"))

            # Check other CLI rules directories
            for cli_key in ("claude", "cursor"):
                if cli_key in profile.cli_dirs:
                    cli_rules_dir = Path(profile.cli_dirs[cli_key]) / "rules"
                    if cli_rules_dir.resolve() == primary_rules_dir.resolve():
                        continue
                    actions.append((cli_rules_dir / f"{item.name}.mdc", target_mdc, "link", f"{item.name}.mdc", "rule"))

        elif item.kind == "skill":
            skill_source_dir = pack_dir / "skills" / item.name
            primary_skill_dir = agents_base / "skills" / item.name
            for file_path in sorted(skill_source_dir.rglob("*")):
                if file_path.is_file():
                    rel = file_path.relative_to(skill_source_dir)
                    actions.append((primary_skill_dir / rel, file_path, "file", f"{item.name}/{rel.as_posix()}", "skill"))

            for cli_key in ("claude", "cursor"):
                if cli_key in profile.cli_dirs:
                    cli_skills_dir = Path(profile.cli_dirs[cli_key]) / "skills" / item.name
                    if cli_skills_dir.parent.resolve() == primary_skill_dir.parent.resolve():
                        continue
                    for file_path in sorted(skill_source_dir.rglob("*")):
                        if file_path.is_file():
                            rel = file_path.relative_to(skill_source_dir)
                            actions.append((cli_skills_dir / rel, file_path, "file", f"{item.name}/{rel.as_posix()}", "skill"))

    return actions


def apply_packs(
    packs: list[Pack | str | Path] | None = None,
    dry_run: bool = True,
    replace: bool = False,
    home: Path | None = None,
    profile: MachineProfile | None = None,
    manifest_path: Path | None = None,
) -> ApplyResult:
    """Applies packs to the environment. Defaults to dry_run=True.

    Protects kit canonical files (nlink > 1) by refusing overwrite.
    Replaces nlink == 1 files only when replace=True, backing up to ~/.aiwork/backups/<timestamp>/.
    Writes rules as .mdc and hardlinks (or copies) to Claude and Gemini rules paths.
    Recursively writes skills to skills/<name>/.
    Rolls back automatically on failure.
    """
    if profile is None:
        profile = load_machine_profile(home=home)

    loaded_packs: list[Pack] = []
    if packs is None:
        for pack_id in profile.enabled_packs:
            found = find_pack(pack_id, libraries=profile.libraries, home=home)
            if not found:
                raise PackError(f"Enabled pack '{pack_id}' not found in libraries: {profile.libraries}")
            loaded_packs.append(found)
    else:
        for p in packs:
            if isinstance(p, Pack):
                loaded_packs.append(p)
            elif isinstance(p, (str, Path)):
                pth = Path(p)
                if pth.is_dir():
                    loaded_packs.append(validate_pack(pth))
                elif pth.is_file() and pth.suffix.lower() == ".zip":
                    import tempfile
                    td = Path(tempfile.mkdtemp(prefix="aiwork_pack_"))
                    safe_extract_zip(pth, td)
                    loaded_packs.append(validate_pack(td))
                else:
                    found = find_pack(str(p), libraries=profile.libraries, home=home)
                    if not found:
                        raise PackError(f"Pack '{p}' not found in libraries")
                    loaded_packs.append(found)

    manifest = load_manifest(path=manifest_path, home=home)
    plans: dict[str, list[dict[str, Any]]] = {
        "add": [],
        "replace": [],
        "conflicts": [],
        "dirs_to_create": [],
    }
    dirs_to_create: set[str] = set()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_base = (home or aiwork_home()) / "backups" / timestamp

    all_actions: list[tuple[Path, Path, Literal["file", "link", "copy"], str, str, Pack]] = []
    for pack in loaded_packs:
        actions = _resolve_target_actions(pack, profile, home=home)
        for target_p, source_p, mode, item_name, item_kind in actions:
            all_actions.append((target_p, source_p, mode, item_name, item_kind, pack))

            curr = target_p.parent
            while curr and not curr.exists() and curr != curr.parent:
                dirs_to_create.add(str(curr))
                curr = curr.parent

            in_manifest = manifest.get(target_p) is not None
            if target_p.exists():
                st = target_p.stat()
                if not in_manifest:
                    if st.st_nlink > 1:
                        plans["conflicts"].append({
                            "target_path": str(target_p),
                            "source_pack": pack.id,
                            "item": item_name,
                            "kind": item_kind,
                            "reason": f"Hardlink kit protection: existing file has st_nlink={st.st_nlink} > 1 and is not in manifest; refusing overwrite to protect kit canonical source.",
                        })
                    elif not replace:
                        plans["conflicts"].append({
                            "target_path": str(target_p),
                            "source_pack": pack.id,
                            "item": item_name,
                            "kind": item_kind,
                            "reason": "File exists and is not in manifest (replace=False). Pass replace=True to overwrite and backup.",
                        })
                    else:
                        plans["replace"].append({
                            "target_path": str(target_p),
                            "source_pack": pack.id,
                            "item": item_name,
                            "kind": item_kind,
                            "mode": mode,
                        })
                else:
                    plans["replace"].append({
                        "target_path": str(target_p),
                        "source_pack": pack.id,
                        "item": item_name,
                        "kind": item_kind,
                        "mode": mode,
                    })
            else:
                plans["add"].append({
                    "target_path": str(target_p),
                    "source_pack": pack.id,
                    "item": item_name,
                    "kind": item_kind,
                    "mode": mode,
                })

    plans["dirs_to_create"] = sorted(list(dirs_to_create))
    result = ApplyResult(plans=plans, dry_run=dry_run, success=True)

    if dry_run:
        return result

    if plans["conflicts"]:
        reasons = "\n".join(f"  - {c['target_path']}: {c['reason']}" for c in plans["conflicts"])
        raise PackError(f"Cannot apply packs due to conflicts:\n{reasons}")

    # Real apply execution with rollback
    written_files: list[Path] = []
    restorations: list[tuple[Path, Path]] = []
    created_directories: list[Path] = []
    entries_to_add: list[ManifestEntry] = []

    def _ensure_dir_created(d: Path):
        parts = []
        curr = d
        while curr and not curr.exists() and curr != curr.parent:
            parts.append(curr)
            curr = curr.parent
        for p in reversed(parts):
            p.mkdir(parents=True, exist_ok=True)
            created_directories.append(p)

    try:
        backups_map: dict[str, str] = {}
        if replace:
            for target_p, _, _, _, _, _ in all_actions:
                if target_p.exists() and not manifest.get(target_p):
                    target_norm = normalize_target_path(target_p)
                    if target_norm not in backups_map:
                        backup_base.mkdir(parents=True, exist_ok=True)
                        h = sha256_file(target_p)[:8]
                        bak_file = backup_base / f"{target_p.name}_{h}"
                        shutil.copy2(target_p, bak_file)
                        backups_map[target_norm] = str(bak_file)
                        restorations.append((target_p, bak_file))

        for target_p, source_p, mode, item_name, item_kind, pack in all_actions:
            _ensure_dir_created(target_p.parent)
            existing_entry = manifest.get(target_p)
            backup_path = existing_entry.backup_path if existing_entry else backups_map.get(normalize_target_path(target_p))

            final_mode = mode
            if mode == "file":
                tmp_file = target_p.parent / f"{target_p.name}.{os.getpid()}.tmp"
                tmp_file.write_bytes(source_p.read_bytes())
                os.replace(tmp_file, target_p)
                written_files.append(target_p)
            elif mode == "link":
                if target_p.exists():
                    target_p.unlink()
                try:
                    os.link(source_p, target_p)
                    final_mode = "link"
                except OSError:
                    shutil.copy2(source_p, target_p)
                    final_mode = "copy"
                written_files.append(target_p)

            sha = sha256_file(target_p)
            entry = ManifestEntry(
                target_path=str(target_p),
                sha256=sha,
                source_pack=pack.id,
                item=item_name,
                mode=final_mode,
                backup_path=backup_path,
            )
            entries_to_add.append(entry)

        for entry in entries_to_add:
            manifest.add(entry)
        manifest.save(manifest_path, home=home)

        result.dry_run = False
        result.applied_entries = entries_to_add
        if restorations:
            result.backup_dir = str(backup_base)
        return result

    except Exception as exc:
        for p in reversed(written_files):
            if p.exists() or p.is_symlink():
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
        for orig, bak in reversed(restorations):
            try:
                if bak.is_file():
                    shutil.copy2(bak, orig)
            except OSError:
                pass
        for d in reversed(created_directories):
            if d.is_dir() and not any(d.iterdir()):
                try:
                    d.rmdir()
                except OSError:
                    pass
        raise PackError(f"Apply failed and was rolled back: {exc}") from exc


def undo_packs(
    pack_ids: list[str] | None = None,
    home: Path | None = None,
    manifest_path: Path | None = None,
) -> UndoResult:
    """Restores applied packs from manifest.

    Unmodified files are safely unlinked or restored from backup.
    Modified files are retained and reported as 'modified'.
    Clears manifest records for undone items. Never deletes files outside manifest.
    """
    manifest = load_manifest(path=manifest_path, home=home)
    result = UndoResult()

    if pack_ids is not None:
        target_entries = [e for e in manifest.entries if e.source_pack in pack_ids]
    else:
        target_entries = list(manifest.entries)

    removed_paths: list[Path] = []
    profile = load_machine_profile(home=home)
    base_home = home or user_home()
    protected_roots = {
        Path(profile.cli_dirs.get(k, base_home / f".{k}")).resolve()
        for k in ["agents", "claude", "cursor", "gemini"]
    }
    for pr in list(protected_roots):
        protected_roots.add((pr / "agents").resolve())
        protected_roots.add((pr / "rules").resolve())
        protected_roots.add((pr / "skills").resolve())
        protected_roots.add((pr / ".agents").resolve())
        protected_roots.add((pr / ".agents" / "rules").resolve())

    for entry in target_entries:
        target = Path(entry.target_path)
        if target.exists():
            current_sha = sha256_file(target)
            if current_sha == entry.sha256:
                if entry.backup_path and Path(entry.backup_path).is_file():
                    shutil.copy2(entry.backup_path, target)
                    result.restored.append(str(target))
                else:
                    target.unlink()
                    result.removed.append(str(target))
                removed_paths.append(target)
                manifest.remove(entry.target_path)
            else:
                result.modified.append(str(target))
                manifest.remove(entry.target_path)
        else:
            if entry.backup_path and Path(entry.backup_path).is_file():
                shutil.copy2(entry.backup_path, target)
                result.restored.append(str(target))
            else:
                result.missing.append(str(target))
            manifest.remove(entry.target_path)

    for p in removed_paths:
        curr = p.parent
        while curr and curr != curr.parent and curr.resolve() not in protected_roots:
            if curr.is_dir() and not any(curr.iterdir()):
                try:
                    curr.rmdir()
                except OSError:
                    break
                curr = curr.parent
            else:
                break

    save_manifest(manifest, path=manifest_path, home=home)
    return result


def packs_status(home: Path | None = None) -> dict[str, Any]:
    profile = load_machine_profile(home=home)
    manifest = load_manifest(home=home)
    entries_status = []
    for entry in manifest.entries:
        p = Path(entry.target_path)
        if not p.exists():
            st = "missing"
        elif sha256_file(p) != entry.sha256:
            st = "modified"
        else:
            st = "intact"
        entries_status.append({
            "target_path": entry.target_path,
            "source_pack": entry.source_pack,
            "mode": entry.mode,
            "status": st,
            "backup_path": entry.backup_path,
        })
    cli_dirs_status = {}
    for k, v in profile.cli_dirs.items():
        p = Path(v)
        is_link = p.is_symlink() or (os.name == "nt" and p.is_dir() and bool(os.stat(p).st_file_attributes & 0x400) if p.exists() else False)
        cli_dirs_status[k] = {
            "path": v,
            "exists": p.exists(),
            "realpath": str(p.resolve()) if p.exists() else v,
            "is_link": is_link,
        }
    return {
        "machine_name": profile.name,
        "scope": profile.scope,
        "libraries": profile.libraries,
        "enabled_packs": profile.enabled_packs,
        "applied_count": len(manifest.entries),
        "manifest_path": str(applied_manifest_path(home)),
        "entries": entries_status,
        "cli_dirs": cli_dirs_status,
    }


def doctor_check(home: Path | None = None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    base_home = home or aiwork_home()
    profile = load_machine_profile(home=home)
    manifest = load_manifest(home=home)

    # 1. Git tree check
    in_git = False
    curr = base_home.resolve()
    while curr != curr.parent:
        if (curr / ".git").exists():
            in_git = True
            break
        curr = curr.parent
    if in_git:
        checks.append({
            "name": "git_contamination",
            "status": "warning",
            "message": f"Machine state directory ({base_home}) is inside a git working tree! State files (machine.yaml, applied.json) should not be committed.",
        })
    else:
        checks.append({
            "name": "git_contamination",
            "status": "ok",
            "message": f"Machine state directory ({base_home}) is clean (outside git repo).",
        })

    # 2. Libraries check
    for lib in profile.libraries:
        p = Path(lib).expanduser().resolve()
        if p.is_dir():
            checks.append({
                "name": f"library:{lib}",
                "status": "ok",
                "message": f"Library exists: {p}",
            })
        else:
            checks.append({
                "name": f"library:{lib}",
                "status": "warning",
                "message": f"Library directory does not exist: {p}",
            })

    # 3. Enabled packs check
    for pack_id in profile.enabled_packs:
        pack = find_pack(pack_id, libraries=profile.libraries, home=home)
        if pack:
            checks.append({
                "name": f"pack:{pack_id}",
                "status": "ok",
                "message": f"Enabled pack '{pack_id}' found in libraries.",
            })
        else:
            checks.append({
                "name": f"pack:{pack_id}",
                "status": "error",
                "message": f"Enabled pack '{pack_id}' was NOT found in any configured library!",
            })

    # 4. CLI directories
    for cli_name, dir_str in profile.cli_dirs.items():
        p = Path(dir_str).expanduser()
        status_str = f"exists (realpath: {p.resolve()})" if p.exists() else "does not exist yet"
        checks.append({
            "name": f"cli_dir:{cli_name}",
            "status": "ok" if p.exists() else "notice",
            "message": f"CLI '{cli_name}': {p} -> {status_str}",
        })

    # 5. Manifest integrity
    modified_count = 0
    missing_count = 0
    for entry in manifest.entries:
        tp = Path(entry.target_path)
        if not tp.exists():
            missing_count += 1
        elif sha256_file(tp) != entry.sha256:
            modified_count += 1
    if modified_count == 0 and missing_count == 0:
        checks.append({
            "name": "manifest_integrity",
            "status": "ok",
            "message": f"All {len(manifest.entries)} applied files match manifest hashes.",
        })
    else:
        checks.append({
            "name": "manifest_integrity",
            "status": "warning",
            "message": f"Manifest drift: {modified_count} modified, {missing_count} missing.",
        })

    return checks


# =====================================================================
# Role Definitions & Skill Pool Scanning (Phase 2 P2-3)
# =====================================================================

SAFE_ROLE_PATH_RE: re.Pattern = re.compile(r"^[A-Za-z0-9._:/-]+$")


class RoleDefDumper(yaml.SafeDumper):
    pass


def _quote_colon_str(dumper: yaml.SafeDumper, data: str):
    if ":" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


RoleDefDumper.add_representer(str, _quote_colon_str)


class RoleDef(BaseModel):
    name: str
    description: str
    skills: list[str] = Field(default_factory=list)
    body: str = ""

    def get_missing_skills(self, pool: dict[str, Any]) -> list[str]:
        return get_missing_skills(self.skills, pool)

    def check_skills(self, pool: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return check_role_skills(self.skills, pool)


def parse_role_def(content: str) -> RoleDef:
    fm, body = parse_frontmatter(content)
    if fm is None:
        raise ValueError("Role definition missing YAML frontmatter")
    if not isinstance(fm, dict):
        raise ValueError("Role definition frontmatter must be a YAML mapping")

    name = fm.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("Role definition frontmatter missing or invalid 'name'")
    if not ROLE_ID_RE.match(name):
        raise ValueError(f"Invalid role name '{name}', must match {ROLE_ID_RE.pattern}")

    description = fm.get("description")
    if not description or not isinstance(description, str) or not description.strip():
        raise ValueError("Role definition frontmatter missing or empty 'description'")

    skills_raw = fm.get("skills")
    skills: list[str] = []
    if skills_raw is not None:
        if not isinstance(skills_raw, list) or not all(isinstance(s, str) for s in skills_raw):
            raise ValueError("Role definition frontmatter 'skills' must be a list of strings")
        skills = list(skills_raw)

    return RoleDef(
        name=name,
        description=description,
        skills=skills,
        body=(body or "").strip(),
    )


deserialize_role_def = parse_role_def


def dump_role_def(role_def: RoleDef) -> str:
    if not ROLE_ID_RE.match(role_def.name):
        raise ValueError(f"Invalid role name '{role_def.name}', must match {ROLE_ID_RE.pattern}")
    if not role_def.description or not role_def.description.strip():
        raise ValueError("Role definition description cannot be empty")

    meta: dict[str, Any] = {
        "name": role_def.name,
        "description": role_def.description,
    }
    if role_def.skills:
        meta["skills"] = list(role_def.skills)

    fm_yaml = yaml.dump(
        meta,
        Dumper=RoleDefDumper,
        sort_keys=False,
        allow_unicode=True,
    ).strip()

    body = role_def.body.strip()
    if body:
        return f"---\n{fm_yaml}\n---\n\n{body}\n"
    return f"---\n{fm_yaml}\n---\n"


serialize_role_def = dump_role_def


def load_role_def(path: Path | str) -> RoleDef:
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Role definition file not found: {p}")
    content = p.read_text(encoding="utf-8")
    return parse_role_def(content)


def save_role_def(
    role_def: RoleDef,
    path: Path | str,
    pool: dict[str, Any] | None = None,
) -> Path:
    p = Path(path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    content = dump_role_def(role_def)
    tmp_file = p.parent / f"{p.name}.{os.getpid()}.tmp"
    tmp_file.write_text(content, encoding="utf-8")
    os.replace(tmp_file, p)
    return p


def scan_skills_pool(
    home: Path | None = None,
    profile: MachineProfile | None = None,
    libraries: list[str | Path] | None = None,
) -> dict[str, dict[str, Any]]:
    """Scans the skill pool consisting of:
    - External skills: ~/.agents/skills/*/SKILL.md
    - Pack skills: skills/*/SKILL.md in enabled packs across configured libraries.

    Returns a dict mapping skill_name to skill metadata (name, description, source, path).
    """
    if profile is None:
        profile = load_machine_profile(home=home)

    pool: dict[str, dict[str, Any]] = {}
    base_home = home or user_home()
    agents_dir = Path(profile.cli_dirs.get("agents", base_home / ".agents"))
    external_skills_dir = agents_dir / "skills"

    if external_skills_dir.is_dir():
        for skill_dir in sorted(external_skills_dir.iterdir()):
            if skill_dir.is_dir():
                skill_md = skill_dir / "SKILL.md"
                if skill_md.is_file():
                    try:
                        text = skill_md.read_text(encoding="utf-8")
                        fm, _ = parse_frontmatter(text)
                        s_name = skill_dir.name
                        s_desc = ""
                        if fm and isinstance(fm, dict):
                            s_name = fm.get("name") or s_name
                            s_desc = fm.get("description") or ""
                        pool[s_name] = {
                            "name": s_name,
                            "description": str(s_desc),
                            "source": "external",
                            "path": skill_md.resolve().as_posix(),
                        }
                    except Exception:
                        pass

    lib_list = libraries or profile.libraries
    for pack_id in profile.enabled_packs:
        pack = find_pack(pack_id, libraries=lib_list, home=home)
        if pack and pack.path:
            pack_skills_dir = pack.path / "skills"
            if pack_skills_dir.is_dir():
                for skill_dir in sorted(pack_skills_dir.iterdir()):
                    if skill_dir.is_dir():
                        skill_md = skill_dir / "SKILL.md"
                        if skill_md.is_file():
                            try:
                                text = skill_md.read_text(encoding="utf-8")
                                fm, _ = parse_frontmatter(text)
                                s_name = skill_dir.name
                                s_desc = ""
                                if fm and isinstance(fm, dict):
                                    s_name = fm.get("name") or s_name
                                    s_desc = fm.get("description") or ""
                                pool[s_name] = {
                                    "name": s_name,
                                    "description": str(s_desc),
                                    "source": f"pack:{pack.id}",
                                    "path": skill_md.resolve().as_posix(),
                                }
                            except Exception:
                                pass

    return pool


def check_role_skills(
    skills: list[str],
    pool: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Checks a list of skill names against the skills pool.

    Returns a dict mapping skill_name to status info:
    - 'available': True/False
    - 'status': 'ok' if available else '缺'
    - 'source': source from pool if available else None
    - 'description': description from pool if available else ''
    """
    res: dict[str, dict[str, Any]] = {}
    for s in skills:
        if s in pool:
            res[s] = {
                "name": s,
                "available": True,
                "status": "ok",
                "source": pool[s].get("source"),
                "description": pool[s].get("description", ""),
            }
        else:
            res[s] = {
                "name": s,
                "available": False,
                "status": "缺",
                "source": None,
                "description": "",
            }
    return res


def get_missing_skills(skills: list[str], pool: dict[str, Any]) -> list[str]:
    return [s for s in skills if s not in pool]


def find_role_definition(
    role_id: str,
    home: Path | None = None,
    profile: MachineProfile | None = None,
    libraries: list[str | Path] | None = None,
) -> Path | None:
    """Finds the definition file for a role.

    Checks in order:
    1. ~/.agents/agents/<id>.md
    2. Enabled packs in library: <pack>/agents/<id>.md
    3. Other packs in library: <pack>/agents/<id>.md
    """
    if profile is None:
        profile = load_machine_profile(home=home)

    base_home = home or user_home()
    agents_dir = Path(profile.cli_dirs.get("agents", base_home / ".agents")) / "agents"
    primary_target = agents_dir / f"{role_id}.md"
    if primary_target.is_file():
        return primary_target.resolve()

    lib_list = libraries or profile.libraries
    for pack_id in profile.enabled_packs:
        pack = find_pack(pack_id, libraries=lib_list, home=home)
        if pack and pack.path:
            candidate = pack.path / "agents" / f"{role_id}.md"
            if candidate.is_file():
                return candidate.resolve()

    for pack in list_packs(libraries=lib_list, home=home):
        if pack and pack.path:
            candidate = pack.path / "agents" / f"{role_id}.md"
            if candidate.is_file():
                return candidate.resolve()

    return None


def is_valid_role_path(path: Path | str) -> bool:
    if isinstance(path, Path):
        posix_path = path.as_posix()
    else:
        posix_path = str(path).replace("\\", "/")
    return bool(SAFE_ROLE_PATH_RE.match(posix_path))


def get_role_delivery_status(role_file: Path | str | None) -> tuple[str, str]:
    if role_file is None:
        return "no", "none"
    p = Path(role_file).resolve()
    if not p.is_file():
        return "no", "none"
    posix_str = p.as_posix()
    if is_valid_role_path(p):
        return posix_str, "prompt-path"
    return posix_str, "none"


def inject_role_header(
    prompt: str,
    role_file: str | Path | None = None,
    delivery: str | None = None,
) -> str:
    """Injects role principles header into prompt if conditions are met.

    Header format:
    @<role_file_absolute_path>
    請依上面這個角色檔的工作原則執行下面的任務。

    <original_prompt>

    Rules:
    - If role_file is None or delivery is "none": returns prompt verbatim unchanged.
    - Role file path is converted to a forward-slash '/' absolute path.
    - Path must strictly match ^[A-Za-z0-9._:/-]+$.
    - If path contains whitespace or non-ASCII characters: does NOT add header,
      emits a warning, and returns prompt unchanged.
    """
    if not role_file or delivery == "none":
        return prompt

    if isinstance(role_file, Path):
        posix_path = role_file.resolve().as_posix()
    else:
        raw_str = str(role_file).replace("\\", "/")
        p = Path(raw_str)
        if not p.is_absolute():
            posix_path = p.resolve().as_posix()
        else:
            posix_path = p.as_posix()

    if not is_valid_role_path(posix_path):
        import warnings
        warnings.warn(
            f"Role definition path '{posix_path}' contains invalid characters or whitespace; falling back to delivery: none",
            UserWarning,
            stacklevel=2,
        )
        return prompt

    return f"@{posix_path}\n請依上面這個角色檔的工作原則執行下面的任務。\n\n{prompt}"


build_role_prompt = inject_role_header


def stage_upload(
    data: bytes | BinaryIO,
    filename: str | None = None,
    home: Path | None = None,
) -> tuple[str, list[dict[str, Any]], bool, str]:
    """Safely stages an uploaded zip archive or single file into ~/.aiwork/staging/<upload_id>/.

    Returns:
        (upload_id, file_list, has_scripts, warning_message)
    """
    if hasattr(data, "read"):
        content_bytes = data.read()
    else:
        content_bytes = bytes(data)

    upload_id = uuid.uuid4().hex[:12]
    staging_base = aiwork_home(home) / "staging"
    staging_base.mkdir(parents=True, exist_ok=True)
    staging_dir = staging_base / upload_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    is_zip = (
        content_bytes.startswith(b"PK\x03\x04")
        or (filename and filename.lower().endswith(".zip"))
    )

    try:
        if is_zip:
            safe_extract_zip(content_bytes, staging_dir)
        else:
            raw_name = (filename or "file.txt").replace("\\", "/")
            name_parts = [p for p in raw_name.split("/") if p and p != "."]
            if not name_parts or any(p == ".." or ":" in p for p in name_parts):
                raise PackSecurityError(f"Invalid path traversal in filename: {filename}")
            for p in name_parts:
                stem = Path(p).stem.upper()
                if stem in WINDOWS_RESERVED_NAMES:
                    raise PackSecurityError(f"Windows reserved filename component: {p}")

            dest_file = staging_dir
            for part in name_parts[:-1]:
                dest_file = dest_file / part
                dest_file.mkdir(parents=True, exist_ok=True)
            target_file = dest_file / name_parts[-1]

            ext = target_file.suffix.lower()
            if ext in FORBIDDEN_EXTENSIONS:
                raise PackSecurityError(f"Forbidden file extension: {ext}")
            if ext not in ALLOWED_EXTENSIONS and ext not in SKILL_SCRIPT_EXTENSIONS:
                raise PackSecurityError(f"Unauthorized file extension: {ext}")

            if len(content_bytes) > MAX_SINGLE_FILE_SIZE:
                raise PackSecurityError(
                    f"File exceeds maximum single file size limit ({MAX_SINGLE_FILE_SIZE} bytes)"
                )
            if (ext in (".md", ".mdc") and "rules" in raw_name) and len(content_bytes) > MAX_RULE_FILE_SIZE:
                raise PackValidationError(
                    f"Rule file exceeds 64 KB limit ({len(content_bytes)} bytes)"
                )

            try:
                content_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PackSecurityError("Uploaded file is not valid UTF-8 text") from exc

            target_file.write_bytes(content_bytes)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    file_list: list[dict[str, Any]] = []
    has_scripts = False
    for f in sorted(staging_dir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(staging_dir).as_posix()
            ext = f.suffix.lower()
            is_script = ext in SKILL_SCRIPT_EXTENSIONS
            if is_script:
                has_scripts = True

            kind = "other"
            if rel.startswith("agents/") or (ext == ".md" and "agents" in rel):
                kind = "agent"
            elif rel.startswith("rules/") or ext == ".mdc" or "rules" in rel:
                kind = "rule"
            elif rel.startswith("skills/") or "skills" in rel:
                kind = "skill"
            elif rel == "pack.yaml":
                kind = "pack"

            file_list.append({
                "path": rel,
                "size": f.stat().st_size,
                "sha256": sha256_file(f),
                "kind": kind,
                "has_scripts": is_script,
            })

    warning = (
        "注意：包含腳本檔案，這些內容之後會被有 shell 權限的代理讀到"
        if has_scripts
        else ""
    )
    return upload_id, file_list, has_scripts, warning


def commit_pack(
    upload_id: str,
    pack_id: str,
    replace: bool = False,
    library_path: str | Path | None = None,
    home: Path | None = None,
) -> Path:
    """Validates staged upload and moves it into the configured library."""
    if not PACK_ID_RE.match(pack_id):
        raise PackValidationError(f"Invalid pack ID: '{pack_id}'")

    staging_dir = aiwork_home(home) / "staging" / upload_id
    if not staging_dir.is_dir():
        raise PackValidationError(f"Upload '{upload_id}' not found in staging")

    pack_root = staging_dir
    if not (staging_dir / "pack.yaml").is_file():
        subdirs = [d for d in staging_dir.iterdir() if d.is_dir()]
        if len(subdirs) == 1 and (subdirs[0] / "pack.yaml").is_file():
            pack_root = subdirs[0]
        else:
            (staging_dir / "pack.yaml").write_text(
                f"id: {pack_id}\nname: {pack_id}\ndescription: Staged pack\nversion: 1\n",
                encoding="utf-8",
            )

    pack_yaml_path = pack_root / "pack.yaml"
    if pack_yaml_path.is_file():
        raw = yaml.safe_load(pack_yaml_path.read_text(encoding="utf-8")) or {}
        if raw.get("id") != pack_id:
            raw["id"] = pack_id
            pack_yaml_path.write_text(
                yaml.dump(raw, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

    validate_pack(pack_root)

    profile = load_machine_profile(home=home)
    target_lib = Path(library_path or profile.libraries[0]).expanduser().resolve()
    target_lib.mkdir(parents=True, exist_ok=True)
    target_pack_dir = target_lib / pack_id

    if target_pack_dir.exists():
        if not replace:
            raise PackError(
                f"Pack '{pack_id}' already exists in library; specify replace=True to overwrite"
            )
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        bak_dir = aiwork_home(home) / "backups" / "library" / ts / pack_id
        bak_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target_pack_dir), str(bak_dir))

    shutil.copytree(str(pack_root), str(target_pack_dir))
    shutil.rmtree(str(staging_dir), ignore_errors=True)
    return target_pack_dir


def save_local_role(
    role_id: str,
    description: str,
    principles: str,
    skills: list[str] | None = None,
    home: Path | None = None,
) -> Path:
    """Saves or edits a role definition in the default local-roles pack."""
    if not ROLE_ID_RE.match(role_id):
        raise PackValidationError(f"Invalid role ID: '{role_id}'")

    profile = load_machine_profile(home=home)
    manifest = load_manifest(home=home)
    base_home = user_home(home)
    agents_dir = Path(profile.cli_dirs.get("agents", base_home / ".agents")) / "agents"
    ext_file = agents_dir / f"{role_id}.md"

    if ext_file.is_file() and manifest.get(ext_file) is None:
        raise PackSecurityError(
            f"Role '{role_id}' is externally managed at {ext_file} and cannot be modified."
        )

    lib_dir = Path(profile.libraries[0]).expanduser().resolve()
    local_roles_dir = lib_dir / "local-roles"
    local_roles_dir.mkdir(parents=True, exist_ok=True)
    pack_yaml = local_roles_dir / "pack.yaml"
    if not pack_yaml.is_file():
        pack_yaml.write_text(
            "id: local-roles\nname: Local Roles\ndescription: Locally created and edited roles\nversion: 1\n",
            encoding="utf-8",
        )

    roles_dir = local_roles_dir / "agents"
    roles_dir.mkdir(parents=True, exist_ok=True)
    target_role_file = roles_dir / f"{role_id}.md"

    role_def = RoleDef(
        name=role_id,
        description=description,
        skills=skills or [],
        body=principles,
    )
    save_role_def(role_def, target_role_file)

    if "local-roles" not in profile.enabled_packs:
        profile.enabled_packs.append("local-roles")
        save_machine_profile(profile, home=home)

    return target_role_file


def cleanup_expired_staging(max_age_hours: int = 24, home: Path | None = None) -> int:
    """Removes staging directories older than max_age_hours."""
    staging_base = aiwork_home(home) / "staging"
    if not staging_base.is_dir():
        return 0
    now = datetime.now(timezone.utc).timestamp()
    removed = 0
    for child in staging_base.iterdir():
        if child.is_dir():
            try:
                mtime = child.stat().st_mtime
                if now - mtime > max_age_hours * 3600:
                    shutil.rmtree(str(child), ignore_errors=True)
                    removed += 1
            except OSError:
                pass
    return removed


def probe_path(home: Path | None = None) -> Path:
    return aiwork_home(home) / "probe.json"


def load_probe_results(home: Path | None = None) -> dict[str, Any]:
    p = probe_path(home)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def save_probe_results(data: dict[str, Any], home: Path | None = None) -> Path:
    p = probe_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.parent / f"{p.name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def check_cli_status(agent: str) -> str:
    """Returns 'ok' (logged in), 'not_logged_in', or 'missing'."""
    prog = {"cursor": "agent", "claude": "claude", "gemini": "agy"}.get(agent, agent)
    if shutil.which(prog) is None:
        return "missing"

    if agent == "cursor":
        try:
            cmd = ["cmd", "/c", "agent", "status"] if os.name == "nt" else ["agent", "status"]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            text = (proc.stdout + proc.stderr).lower()
            if "not logged in" in text or "logged out" in text:
                return "not_logged_in"
            if proc.returncode == 0 and "logged in" in text:
                return "ok"
            return "not_logged_in"
        except Exception:
            return "not_logged_in"
    elif agent == "claude":
        try:
            cmd = ["cmd", "/c", "claude", "auth", "status"] if os.name == "nt" else ["claude", "auth", "status"]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            text = (proc.stdout + proc.stderr).lower()
            if '"loggedin": false' in text or '"loggedin":false' in text:
                return "not_logged_in"
            if proc.returncode == 0:
                return "ok"
            return "not_logged_in"
        except Exception:
            return "not_logged_in"
    elif agent == "gemini":
        status_file = aiwork_home().parent / "data" / "agent_status.json"
        if status_file.is_file():
            try:
                st = json.loads(status_file.read_text(encoding="utf-8"))
                if st.get("gemini") is False:
                    return "not_logged_in"
            except Exception:
                pass
        return "ok"

    return "missing"


def probe_single_agent(
    agent: str,
    home: Path | None = None,
    workdir: Path | None = None,
    role_file_override: Path | None = None,
    adapter_fn: Any = None,
) -> dict[str, Any]:
    """Probes a single agent CLI to verify delivery of role principles."""
    now_iso = datetime.now(timezone.utc).isoformat()
    cli_state = check_cli_status(agent)
    if cli_state == "missing":
        return {
            "status": "missing",
            "label": "沒裝",
            "passed": False,
            "checked_at": now_iso,
            "model": None,
            "detail": f"Executable for agent '{agent}' not found in PATH",
        }
    if cli_state == "not_logged_in":
        return {
            "status": "not_logged_in",
            "label": "未登入",
            "passed": False,
            "checked_at": now_iso,
            "model": None,
            "detail": f"Agent '{agent}' CLI is not logged in",
        }

    model = None
    try:
        from aiwork.dispatch import load_models_catalog, load_roles

        roles, _ = load_roles()
        for r in roles.values():
            if r.agent == agent:
                model = r.model
                break
        if not model:
            cat, _, _ = load_models_catalog()
            if agent in cat and cat[agent]:
                m0 = cat[agent][0]
                model = m0["id"] if isinstance(m0, dict) else str(m0)
    except Exception:
        pass
    if not model:
        model = {
            "cursor": "composer-2.5",
            "claude": "claude-opus-5-5",
            "gemini": "gemini-3.8-flash-high",
        }.get(agent, "default")

    secret = f"[probe-{uuid.uuid4()}]"
    probe_dir = aiwork_home(home) / "staging" / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    temp_role_file = probe_dir / f"probe_{agent}_{uuid.uuid4().hex[:8]}.md"

    role_content = f"""---
name: probe-{agent}
description: Temporary probe role
---
# 工作原則
你的回覆必須包含暗號：{secret}
"""
    temp_role_file.write_text(role_content, encoding="utf-8")

    try:
        target_role = (
            role_file_override if role_file_override is not None else temp_role_file
        )
        delivery_path, delivery = get_role_delivery_status(target_role)
        min_prompt = "請簡短回覆一句話。"
        prompt = build_role_prompt(
            min_prompt,
            role_file=delivery_path if delivery != "none" else None,
            delivery=delivery,
        )

        if adapter_fn is not None:
            res = adapter_fn(
                model=model,
                prompt=prompt,
                cwd=str(workdir or Path.cwd()),
                timeout_sec=60,
            )
        elif agent == "cursor":
            from aiwork.adapters.cursor import run_cursor

            res = run_cursor(
                model=model,
                prompt=prompt,
                cwd=str(workdir or Path.cwd()),
                timeout_sec=60,
            )
        elif agent == "claude":
            from aiwork.adapters.claude import run_claude

            res = run_claude(
                model=model,
                prompt=prompt,
                cwd=str(workdir or Path.cwd()),
                timeout_sec=60,
            )
        elif agent == "gemini":
            from aiwork.adapters.gemini import run_gemini

            res = run_gemini(
                model=model,
                prompt=prompt,
                cwd=str(workdir or Path.cwd()),
                timeout_sec=60,
            )
        else:
            return {
                "status": "failed",
                "label": "未通過",
                "passed": False,
                "checked_at": now_iso,
                "model": model,
                "detail": f"Unknown agent '{agent}'",
            }

        reply = (getattr(res, "final_text", None) or "") + "\n" + (getattr(res, "stdout", "") or "")
        if secret in reply:
            return {
                "status": "passed",
                "label": "通過",
                "passed": True,
                "checked_at": now_iso,
                "model": model,
                "detail": "",
            }
        else:
            return {
                "status": "failed",
                "label": "未通過",
                "passed": False,
                "checked_at": now_iso,
                "model": model,
                "detail": getattr(res, "error_text", "") or "暗號未出現在回答中",
            }
    except Exception as exc:
        return {
            "status": "failed",
            "label": "未通過",
            "passed": False,
            "checked_at": now_iso,
            "model": model,
            "detail": str(exc),
        }
    finally:
        try:
            if temp_role_file.is_file():
                temp_role_file.unlink()
        except OSError:
            pass


def run_probe(
    agent: str | None = None,
    home: Path | None = None,
    workdir: Path | None = None,
    role_file_override: Path | None = None,
    adapter_fn: Any = None,
) -> dict[str, Any]:
    """Runs delivery probe against agent CLIs and updates probe.json."""
    agents_to_probe = [agent] if agent else ["cursor", "claude", "gemini"]
    existing = load_probe_results(home=home)
    now_iso = datetime.now(timezone.utc).isoformat()
    existing["updated_at"] = now_iso
    results_map = existing.get("results")
    if not isinstance(results_map, dict):
        results_map = {}
        existing["results"] = results_map

    for ag in agents_to_probe:
        res = probe_single_agent(
            agent=ag,
            home=home,
            workdir=workdir,
            role_file_override=role_file_override,
            adapter_fn=adapter_fn,
        )
        results_map[ag] = res
        existing[ag] = res

    save_probe_results(existing, home=home)
    return existing


