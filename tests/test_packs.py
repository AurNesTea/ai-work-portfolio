from __future__ import annotations

import io
import os
import stat
import zipfile
from pathlib import Path

import pytest

from aiwork.packs import (
    ALLOWED_EXTENSIONS,
    FORBIDDEN_EXTENSIONS,
    ITEM_NAME_RE,
    PACK_ID_RE,
    ROLE_ID_RE,
    SKILL_SCRIPT_EXTENSIONS,
    ExtractResult,
    Manifest,
    ManifestEntry,
    Pack,
    PackItem,
    PackSecurityError,
    PackValidationError,
    applied_manifest_path,
    load_manifest,
    normalize_target_path,
    parse_frontmatter,
    safe_extract_zip,
    save_manifest,
    validate_pack,
)


def _create_minimal_pack(
    pack_dir: Path,
    pack_id: str = "core-pack",
    pack_name: str = "core-pack",
    pack_desc: str = "Core starter pack",
    pack_version: int | str = 1,
) -> Path:
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.yaml").write_text(
        f"""id: {pack_id}
name: {pack_name}
description: {pack_desc}
version: {pack_version}
""",
        encoding="utf-8",
    )
    return pack_dir


# =====================================================================
# 1. Regex & Frontmatter Helper Tests
# =====================================================================


def test_id_regexes():
    assert PACK_ID_RE.match("core-pack")
    assert PACK_ID_RE.match("pack_1.0-alpha")
    assert not PACK_ID_RE.match("-bad")
    assert not PACK_ID_RE.match("BAD_UPPER")
    assert not PACK_ID_RE.match("pack with spaces")

    assert ROLE_ID_RE.match("builder")
    assert ROLE_ID_RE.match("planner-2")
    assert not ROLE_ID_RE.match("1st-role")
    assert not ROLE_ID_RE.match("Role-Bad")
    assert not ROLE_ID_RE.match("builder_underscore")

    assert ITEM_NAME_RE.match("00-identity")
    assert ITEM_NAME_RE.match("my_skill.test-1")
    assert not ITEM_NAME_RE.match("Bad/Item")


def test_parse_frontmatter():
    text = """---
name: builder
description: Handles coding
skills:
  - tdd
---
# Instructions
Do work.
"""
    fm, body = parse_frontmatter(text)
    assert fm == {"name": "builder", "description": "Handles coding", "skills": ["tdd"]}
    assert "# Instructions\nDo work." in body

    # No frontmatter
    fm2, body2 = parse_frontmatter("# Just markdown\nNo frontmatter")
    assert fm2 is None
    assert body2.startswith("# Just markdown")

    # Frontmatter without trailing body
    text3 = "---\nname: simple\ndescription: ok\n---"
    fm3, body3 = parse_frontmatter(text3)
    assert fm3 == {"name": "simple", "description": "ok"}
    assert body3 == ""


# =====================================================================
# 2. validate_pack Tests (Valid Cases)
# =====================================================================


def test_validate_valid_pack_full(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "my-pack")

    # Add an agent
    agents_dir = pack_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "builder.md").write_text(
        """---
name: builder
description: Implements code
skills:
  - webapp-testing
---
Builder instructions here.
""",
        encoding="utf-8",
    )

    # Add rules (.md and .mdc)
    rules_dir = pack_dir / "rules"
    rules_dir.mkdir()
    (rules_dir / "00-identity.mdc").write_text(
        """---
description: Identity rule
---
# Identity
Always be concise.
""",
        encoding="utf-8",
    )
    (rules_dir / "01-coding.md").write_text(
        "# Coding standard\nNo frontmatter needed here.",
        encoding="utf-8",
    )

    # Add skills (one with script, one without)
    skills_dir = pack_dir / "skills"
    skills_dir.mkdir()

    # Skill with script
    s1_dir = skills_dir / "test-runner"
    s1_dir.mkdir()
    (s1_dir / "SKILL.md").write_text(
        """---
name: test-runner
description: Runs test suite
---
# Test Runner
""",
        encoding="utf-8",
    )
    (s1_dir / "run.py").write_text("print('running tests')\n", encoding="utf-8")

    # Skill without script
    s2_dir = skills_dir / "doc-sync"
    s2_dir.mkdir()
    (s2_dir / "SKILL.md").write_text(
        """---
name: doc-sync
description: Syncs documentation
---
# Doc Sync
""",
        encoding="utf-8",
    )
    (s2_dir / "template.txt").write_text("template data", encoding="utf-8")

    pack = validate_pack(pack_dir)
    assert pack.id == "core-pack"
    assert pack.name == "core-pack"
    assert pack.has_scripts is True
    assert len(pack.items) == 5

    # Check items
    builder_item = pack.get_item("agent", "builder")
    assert builder_item is not None
    assert builder_item.description == "Implements code"
    assert builder_item.skills == ["webapp-testing"]
    assert builder_item.has_scripts is False
    assert len(builder_item.sha256) == 64

    identity_rule = pack.get_item("rule", "00-identity")
    assert identity_rule is not None
    assert identity_rule.description == "Identity rule"

    coding_rule = pack.get_item("rule", "01-coding")
    assert coding_rule is not None
    assert coding_rule.description == ""

    s1_item = pack.get_item("skill", "test-runner")
    assert s1_item is not None
    assert s1_item.has_scripts is True
    assert s1_item.description == "Runs test suite"

    s2_item = pack.get_item("skill", "doc-sync")
    assert s2_item is not None
    assert s2_item.has_scripts is False


def test_validate_pack_empty_items(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "empty-pack")
    pack = validate_pack(pack_dir)
    assert pack.id == "core-pack"
    assert pack.items == []
    assert pack.has_scripts is False


# =====================================================================
# 3. validate_pack Tests (Invalid Cases)
# =====================================================================


def test_validate_nonexistent_or_file(tmp_path: Path):
    with pytest.raises(PackValidationError, match="does not exist"):
        validate_pack(tmp_path / "not-there")

    single_file = tmp_path / "file.txt"
    single_file.write_text("hello", encoding="utf-8")
    with pytest.raises(PackValidationError, match="not a directory"):
        validate_pack(single_file)


def test_validate_missing_pack_yaml(tmp_path: Path):
    pack_dir = tmp_path / "no-yaml"
    pack_dir.mkdir()
    with pytest.raises(PackValidationError, match="Missing pack.yaml"):
        validate_pack(pack_dir)


def test_validate_pack_yaml_invalid_fields(tmp_path: Path):
    pack_dir = tmp_path / "bad-yaml"
    pack_dir.mkdir()
    (pack_dir / "pack.yaml").write_text(
        """id: Bad_ID!
name: "pack with spaces"
description: ""
""",
        encoding="utf-8",
    )
    with pytest.raises(PackValidationError) as exc:
        validate_pack(pack_dir)
    err = str(exc.value)
    assert "Invalid pack id" in err
    assert "Invalid pack name" in err
    assert "missing or empty 'description'" in err


def test_validate_agent_stem_mismatch(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-agent-mismatch")
    agents_dir = pack_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "builder.md").write_text(
        """---
name: different-name
description: desc
---
""",
        encoding="utf-8",
    )
    with pytest.raises(PackValidationError, match="must equal filename stem"):
        validate_pack(pack_dir)


def test_validate_agent_invalid_role_id(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-bad-role-id")
    agents_dir = pack_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "123invalid.md").write_text(
        """---
name: 123invalid
description: desc
---
""",
        encoding="utf-8",
    )
    with pytest.raises(PackValidationError, match="Invalid role id"):
        validate_pack(pack_dir)


def test_validate_agent_missing_frontmatter(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-no-fm")
    agents_dir = pack_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "planner.md").write_text(
        "# Just title\nNo frontmatter here.",
        encoding="utf-8",
    )
    with pytest.raises(PackValidationError, match="missing frontmatter"):
        validate_pack(pack_dir)


def test_validate_agent_non_utf8(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-non-utf8")
    agents_dir = pack_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "writer.md").write_bytes(b"\xff\xfe\x00\x00")
    with pytest.raises(PackValidationError, match="is not valid UTF-8"):
        validate_pack(pack_dir)


def test_validate_agent_skills_not_list(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-bad-skills")
    agents_dir = pack_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "writer.md").write_text(
        """---
name: writer
description: Writes docs
skills: not-a-list
---
""",
        encoding="utf-8",
    )
    with pytest.raises(PackValidationError, match="'skills' must be a list"):
        validate_pack(pack_dir)


def test_validate_rule_oversize(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-big-rule")
    rules_dir = pack_dir / "rules"
    rules_dir.mkdir()
    (rules_dir / "huge.md").write_text("x" * (65 * 1024), encoding="utf-8")
    with pytest.raises(PackValidationError, match="exceeds 64 KB limit"):
        validate_pack(pack_dir)


def test_validate_rule_duplicate_stem(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-dup-rule")
    rules_dir = pack_dir / "rules"
    rules_dir.mkdir()
    (rules_dir / "same.md").write_text("Rule 1", encoding="utf-8")
    (rules_dir / "same.mdc").write_text("Rule 2", encoding="utf-8")
    with pytest.raises(PackValidationError, match="Duplicate rule stem"):
        validate_pack(pack_dir)


def test_validate_skill_missing_skill_md(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-no-skill-md")
    skills_dir = pack_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "my-skill").mkdir()
    with pytest.raises(PackValidationError, match="Missing SKILL.md"):
        validate_pack(pack_dir)


def test_validate_skill_name_mismatch(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-skill-mismatch")
    skills_dir = pack_dir / "skills"
    skills_dir.mkdir()
    s_dir = skills_dir / "my-skill"
    s_dir.mkdir()
    (s_dir / "SKILL.md").write_text(
        """---
name: other-skill
description: desc
---
""",
        encoding="utf-8",
    )
    with pytest.raises(PackValidationError, match="must equal folder name"):
        validate_pack(pack_dir)


def test_validate_skill_forbidden_extension(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-forbidden-skill")
    skills_dir = pack_dir / "skills"
    skills_dir.mkdir()
    s_dir = skills_dir / "my-skill"
    s_dir.mkdir()
    (s_dir / "SKILL.md").write_text(
        """---
name: my-skill
description: desc
---
""",
        encoding="utf-8",
    )
    (s_dir / "malware.exe").write_bytes(b"MZfakeexe")
    with pytest.raises(PackValidationError, match="Forbidden file extension in skill"):
        validate_pack(pack_dir)


def test_validate_unexpected_top_level(tmp_path: Path):
    pack_dir = _create_minimal_pack(tmp_path / "pack-unexpected")
    (pack_dir / "extra_dir").mkdir()
    (pack_dir / "bad.exe").write_bytes(b"MZ")
    with pytest.raises(PackValidationError) as exc:
        validate_pack(pack_dir)
    assert "Unexpected top-level directory: 'extra_dir'" in str(exc.value)
    assert "Unexpected top-level file: 'bad.exe'" in str(exc.value)


# =====================================================================
# 4. safe_extract_zip Tests
# =====================================================================


def _build_zip_bytes(files: dict[str, bytes | str]) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            if isinstance(content, str):
                zf.writestr(name, content.encode("utf-8"))
            else:
                zf.writestr(name, content)
    return bio.getvalue()


def test_safe_extract_zip_valid(tmp_path: Path):
    target = tmp_path / "extracted"
    zip_data = _build_zip_bytes(
        {
            "my-pack/pack.yaml": "id: my-pack\nname: my-pack\ndescription: ok\n",
            "my-pack/agents/builder.md": "---\nname: builder\ndescription: dev\n---\nBody",
            "my-pack/rules/00-rule.mdc": "# Rule 00",
            "my-pack/skills/analyzer/SKILL.md": "---\nname: analyzer\ndescription: desc\n---\n",
            "my-pack/skills/analyzer/run.py": "print('hello')",
        }
    )

    res = safe_extract_zip(zip_data, target)
    assert isinstance(res, ExtractResult)
    assert res.has_scripts is True
    assert (target / "my-pack/pack.yaml").is_file()
    assert (target / "my-pack/skills/analyzer/run.py").is_file()
    assert len(res) == 5


def test_safe_extract_zip_reject_path_traversal(tmp_path: Path):
    target = tmp_path / "extracted_traversal"
    zip_data = _build_zip_bytes({"../evil.txt": "evil content"})

    with pytest.raises(PackSecurityError, match="Directory traversal"):
        safe_extract_zip(zip_data, target)

    # Verify no residue files left
    assert list(target.iterdir()) == []


def test_safe_extract_zip_reject_absolute_path(tmp_path: Path):
    target = tmp_path / "extracted_abs"
    zip_data = _build_zip_bytes({"/root/evil.txt": "evil"})

    with pytest.raises(PackSecurityError, match="Absolute paths are forbidden"):
        safe_extract_zip(zip_data, target)
    assert list(target.iterdir()) == []


def test_safe_extract_zip_reject_ntfs_stream(tmp_path: Path):
    target = tmp_path / "extracted_ntfs"
    zip_data = _build_zip_bytes({"pack/file.txt:hidden": "secret stream"})

    with pytest.raises(PackSecurityError, match="Illegal character ':'"):
        safe_extract_zip(zip_data, target)
    assert list(target.iterdir()) == []


def test_safe_extract_zip_reject_windows_reserved_names(tmp_path: Path):
    target = tmp_path / "extracted_reserved"

    for bad_name in ["CON.txt", "prn.md", "AUX", "NUL.yaml", "COM1.txt", "sub/lpt9.mdc"]:
        zip_data = _build_zip_bytes({f"pack/{bad_name}": "device name"})
        with pytest.raises(PackSecurityError, match="Windows reserved device name"):
            safe_extract_zip(zip_data, target)
        assert list(target.iterdir()) == []


def test_safe_extract_zip_reject_case_collision(tmp_path: Path):
    target = tmp_path / "extracted_collision"
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("pack/file.md", "version 1")
        zf.writestr("pack/File.md", "version 2")

    with pytest.raises(PackSecurityError, match="Duplicate/case-collision"):
        safe_extract_zip(bio.getvalue(), target)
    assert list(target.iterdir()) == []


def test_safe_extract_zip_reject_symlink(tmp_path: Path):
    target = tmp_path / "extracted_symlink"
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zinfo = zipfile.ZipInfo("pack/symlink_file")
        zinfo.create_system = 3  # Unix
        # S_IFLNK (0o120000)
        zinfo.external_attr = (0o120777) << 16
        zf.writestr(zinfo, "/etc/passwd")

    with pytest.raises(PackSecurityError, match="Symlinks and reparse points are forbidden"):
        safe_extract_zip(bio.getvalue(), target)
    assert list(target.iterdir()) == []


def test_safe_extract_zip_reject_single_file_oversize(tmp_path: Path):
    target = tmp_path / "extracted_oversize"
    big_content = b"a" * (1 * 1024 * 1024 + 10)
    zip_data = _build_zip_bytes({"pack/big.txt": big_content})

    with pytest.raises(PackSecurityError, match="exceeds single file limit"):
        safe_extract_zip(zip_data, target)
    assert list(target.iterdir()) == []


def test_safe_extract_zip_reject_too_many_files(tmp_path: Path):
    target = tmp_path / "extracted_many"
    files = {f"pack/f_{i}.txt": "a" for i in range(301)}
    zip_data = _build_zip_bytes(files)

    with pytest.raises(PackSecurityError, match="exceeds limit of 300"):
        safe_extract_zip(zip_data, target)
    assert list(target.iterdir()) == []


def test_safe_extract_zip_reject_forbidden_extensions(tmp_path: Path):
    target = tmp_path / "extracted_forbidden"
    for ext in FORBIDDEN_EXTENSIONS:
        zip_data = _build_zip_bytes({f"pack/file{ext}": "evil"})
        with pytest.raises(PackSecurityError, match="Forbidden file extension"):
            safe_extract_zip(zip_data, target)
        assert list(target.iterdir()) == []


def test_safe_extract_zip_reject_scripts_outside_skills(tmp_path: Path):
    target = tmp_path / "extracted_scripts_bad"
    zip_data = _build_zip_bytes({"pack/agents/script.py": "print(1)"})

    with pytest.raises(PackSecurityError, match="only allowed inside skills directory"):
        safe_extract_zip(zip_data, target)
    assert list(target.iterdir()) == []


def test_safe_extract_zip_reject_non_utf8(tmp_path: Path):
    target = tmp_path / "extracted_binary"
    zip_data = _build_zip_bytes({"pack/corrupted.txt": b"\x80\x81\x82\x83\xff"})

    with pytest.raises(PackSecurityError, match="contains non-UTF-8 bytes"):
        safe_extract_zip(zip_data, target)
    assert list(target.iterdir()) == []


# =====================================================================
# 5. Manifest Tests (applied.json)
# =====================================================================


def test_manifest_empty_load(tmp_path: Path):
    man_path = tmp_path / "applied.json"
    manifest = load_manifest(man_path)
    assert manifest.version == 1
    assert manifest.entries == []


def test_manifest_add_get_remove_and_save(tmp_path: Path):
    man_path = tmp_path / "test_applied.json"

    entry1 = ManifestEntry(
        target_path="C:/Users/test/.agents/agents/builder.md",
        sha256="abc1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        source_pack="dev-pack",
        item="agents/builder.md",
        mode="file",
    )
    entry2 = ManifestEntry(
        target_path="C:/Users/test/.agents/rules/00-rule.mdc",
        sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef12",
        source_pack="dev-pack",
        item="rules/00-rule.mdc",
        mode="link",
    )

    manifest = Manifest(version=1, entries=[])
    manifest.add(entry1)
    manifest.add(entry2)

    # Lookup
    found = manifest.get("C:/Users/test/.agents/agents/builder.md")
    assert found is not None
    assert found.item == "agents/builder.md"

    # Lookup with different casing / slashes
    found_casing = manifest.get("c:\\users\\test\\.agents\\agents\\builder.md")
    if os.name == "nt":
        assert found_casing is not None
        assert found_casing.item == "agents/builder.md"

    # Find by pack
    pack_entries = manifest.find_by_pack("dev-pack")
    assert len(pack_entries) == 2

    # Save to disk
    manifest.save(man_path)
    assert man_path.is_file()

    # Load back
    loaded = load_manifest(man_path)
    assert len(loaded.entries) == 2
    assert loaded.get("C:/Users/test/.agents/rules/00-rule.mdc") is not None

    # Replace existing entry on add
    updated_entry1 = ManifestEntry(
        target_path="C:/Users/test/.agents/agents/builder.md",
        sha256="updated_sha",
        source_pack="dev-pack",
        item="agents/builder.md",
        mode="copy",
    )
    loaded.add(updated_entry1)
    assert len(loaded.entries) == 2
    assert loaded.get("C:/Users/test/.agents/agents/builder.md").mode == "copy"

    # Remove
    removed = loaded.remove("C:/Users/test/.agents/agents/builder.md")
    assert removed is not None
    assert removed.mode == "copy"
    assert len(loaded.entries) == 1
    assert loaded.get("C:/Users/test/.agents/agents/builder.md") is None


def test_manifest_atomic_save_replaces(tmp_path: Path):
    man_path = tmp_path / "applied.json"
    manifest = Manifest(
        version=1,
        entries=[
            ManifestEntry(
                target_path="/test/path",
                sha256="dummy",
                source_pack="pack-a",
                item="item-a",
                mode="file",
            )
        ],
    )
    save_manifest(manifest, man_path)
    assert man_path.is_file()

    # Verify no tmp files lingering
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0

    # Save second time with new content
    manifest.add(
        ManifestEntry(
            target_path="/test/path2",
            sha256="dummy2",
            source_pack="pack-b",
            item="item-b",
            mode="copy",
        )
    )
    save_manifest(manifest, man_path)

    reloaded = load_manifest(man_path)
    assert len(reloaded.entries) == 2
    assert list(tmp_path.glob("*.tmp")) == []
