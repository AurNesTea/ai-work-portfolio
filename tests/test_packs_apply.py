from __future__ import annotations

import io
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aiwork.cli import app
from aiwork.packs import (
    ApplyResult,
    MachineProfile,
    Manifest,
    ManifestEntry,
    Pack,
    PackError,
    PackItem,
    UndoResult,
    applied_manifest_path,
    apply_packs,
    detect_cli_dirs,
    disable_pack,
    doctor_check,
    enable_pack,
    find_pack,
    list_packs,
    load_machine_profile,
    load_manifest,
    machine_profile_path,
    packs_status,
    save_machine_profile,
    undo_packs,
    validate_pack,
)

runner = CliRunner()


def _create_sample_pack(
    pack_dir: Path,
    pack_id: str = "sample-pack",
    pack_name: str = "sample-pack",
) -> Path:
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.yaml").write_text(
        f"""id: {pack_id}
name: {pack_name}
description: Sample pack for apply testing
version: 1
""",
        encoding="utf-8",
    )

    # 1. Agent
    agents_dir = pack_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "builder.md").write_text(
        """---
name: builder
description: Builder agent
skills:
  - my-tool
---
Work instructions.
""",
        encoding="utf-8",
    )

    # 2. Rule
    rules_dir = pack_dir / "rules"
    rules_dir.mkdir()
    (rules_dir / "00-identity.mdc").write_text(
        """---
description: Identity rule
---
Always be concise.
""",
        encoding="utf-8",
    )

    # 3. Skill
    skill_dir = pack_dir / "skills" / "my-tool"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: my-tool
description: A sample skill
---
Skill instructions.
""",
        encoding="utf-8",
    )
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "tool.py").write_text("print('tool running')\n", encoding="utf-8")

    return pack_dir


# =====================================================================
# 1. Machine Profile & Directory Detection Tests
# =====================================================================


def test_machine_profile_crud(tmp_path: Path):
    home = tmp_path / "home"
    aiwork_dir = tmp_path / "custom_aiwork"
    aiwork_dir.mkdir()

    profile_file = machine_profile_path(aiwork_dir)
    assert not profile_file.exists()

    # Load default profile
    profile = load_machine_profile(home=aiwork_dir)
    assert profile.scope == "global"
    assert profile.enabled_packs == []
    assert len(profile.libraries) >= 1
    assert "agents" in profile.cli_dirs

    # Save and reload
    profile.enabled_packs.append("test-pack")
    save_machine_profile(profile, home=aiwork_dir)
    assert profile_file.exists()

    reloaded = load_machine_profile(home=aiwork_dir)
    assert reloaded.enabled_packs == ["test-pack"]

    # Enable and disable
    enable_pack("second-pack", home=aiwork_dir)
    p2 = load_machine_profile(home=aiwork_dir)
    assert p2.enabled_packs == ["test-pack", "second-pack"]

    disable_pack("test-pack", home=aiwork_dir)
    p3 = load_machine_profile(home=aiwork_dir)
    assert p3.enabled_packs == ["second-pack"]


def test_detect_cli_dirs_and_deduplication(tmp_path: Path):
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(parents=True, exist_ok=True)
    cli_dirs = detect_cli_dirs(home=fake_home)

    assert cli_dirs["agents"] == str(fake_home / ".agents")
    assert cli_dirs["claude"] == str(fake_home / ".claude")
    assert cli_dirs["cursor"] == str(fake_home / ".cursor")
    assert cli_dirs["gemini"] == str(fake_home / ".gemini" / "config")

    # Simulate deduplication where .claude is pointed to .agents
    agents_dir = fake_home / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    profile = MachineProfile(
        cli_dirs={
            "agents": str(agents_dir),
            "claude": str(agents_dir),  # Same realpath
            "cursor": str(agents_dir),  # Same realpath
            "gemini": str(fake_home / ".gemini" / "config"),
        }
    )

    pack_dir = _create_sample_pack(tmp_path / "dedup-pack")
    pack = validate_pack(pack_dir)

    result = apply_packs(packs=[pack], dry_run=True, home=fake_home, profile=profile)
    # The agent builder.md should only appear ONCE in plans["add"], not 3 times!
    agent_adds = [
        item for item in result.plans["add"] if item["kind"] == "agent"
    ]
    assert len(agent_adds) == 1
    assert Path(agent_adds[0]["target_path"]) == agents_dir / "agents" / "builder.md"


# =====================================================================
# 2. Dry-Run Plan Tests
# =====================================================================


def test_apply_packs_dry_run(tmp_path: Path):
    fake_home = tmp_path / "fake_home"
    aiwork_dir = tmp_path / ".aiwork"
    aiwork_dir.mkdir(parents=True, exist_ok=True)

    pack_dir = _create_sample_pack(tmp_path / "sample-pack")
    pack = validate_pack(pack_dir)

    result = apply_packs(
        packs=[pack], dry_run=True, replace=False, home=fake_home
    )

    assert result.dry_run is True
    assert result.success is True
    assert len(result.plans["conflicts"]) == 0
    assert len(result.plans["add"]) >= 5  # agent, rule mdc, rule md, gemini rule md, SKILL.md, tool.py
    assert len(result.plans["dirs_to_create"]) > 0

    # Verify no files were actually created on disk
    assert not (fake_home / ".agents" / "agents" / "builder.md").exists()
    assert not (fake_home / ".agents" / "rules" / "00-identity.mdc").exists()
    assert not (fake_home / ".agents" / "skills" / "my-tool").exists()
    assert not applied_manifest_path(aiwork_dir).exists()


# =====================================================================
# 3. Real Apply & Rule Hardlinks Tests
# =====================================================================


def test_apply_packs_real_apply_and_links(tmp_path: Path):
    fake_home = tmp_path / "fake_home"
    aiwork_dir = tmp_path / ".aiwork"
    aiwork_dir.mkdir(parents=True, exist_ok=True)

    pack_dir = _create_sample_pack(tmp_path / "sample-pack")
    pack = validate_pack(pack_dir)

    result = apply_packs(
        packs=[pack],
        dry_run=False,
        replace=False,
        home=fake_home,
        manifest_path=applied_manifest_path(aiwork_dir),
    )

    assert result.dry_run is False
    assert result.success is True
    assert len(result.applied_entries) >= 5

    # Check agent file
    agent_file = fake_home / ".agents" / "agents" / "builder.md"
    assert agent_file.is_file()
    assert "Builder agent" in agent_file.read_text(encoding="utf-8")

    # Check rule truth file (.mdc)
    rule_mdc = fake_home / ".agents" / "rules" / "00-identity.mdc"
    assert rule_mdc.is_file()
    assert "Always be concise" in rule_mdc.read_text(encoding="utf-8")

    # Check rule hardlinks
    rule_md = fake_home / ".agents" / "rules" / "00-identity.md"
    gemini_rule_md = (
        fake_home / ".gemini" / "config" / ".agents" / "rules" / "00-identity.md"
    )

    assert rule_md.is_file()
    assert gemini_rule_md.is_file()
    assert rule_md.read_text(encoding="utf-8") == rule_mdc.read_text(encoding="utf-8")

    # Check inode or copy fallback tag in manifest
    manifest = load_manifest(home=aiwork_dir)
    md_entry = manifest.get(rule_md)
    assert md_entry is not None
    assert md_entry.mode in ("link", "copy")

    if md_entry.mode == "link":
        assert os.path.samefile(rule_mdc, rule_md)
        assert os.path.samefile(rule_mdc, gemini_rule_md)

    # Check skill files
    skill_md = fake_home / ".agents" / "skills" / "my-tool" / "SKILL.md"
    tool_py = fake_home / ".agents" / "skills" / "my-tool" / "scripts" / "tool.py"
    assert skill_md.is_file()
    assert tool_py.is_file()
    assert "print('tool running')" in tool_py.read_text(encoding="utf-8")

    # Check manifest entries
    assert manifest.get(agent_file) is not None
    assert manifest.get(skill_md) is not None
    assert manifest.get(tool_py) is not None


# =====================================================================
# 4. Undo Tests (Clean, Restored, Retained modified)
# =====================================================================


def test_undo_packs_clean(tmp_path: Path):
    fake_home = tmp_path / "fake_home"
    aiwork_dir = tmp_path / ".aiwork"
    aiwork_dir.mkdir(parents=True, exist_ok=True)

    pack_dir = _create_sample_pack(tmp_path / "sample-pack")
    pack = validate_pack(pack_dir)

    apply_packs(
        packs=[pack],
        dry_run=False,
        replace=False,
        home=fake_home,
        manifest_path=applied_manifest_path(aiwork_dir),
    )

    agent_file = fake_home / ".agents" / "agents" / "builder.md"
    rule_mdc = fake_home / ".agents" / "rules" / "00-identity.mdc"
    skill_dir = fake_home / ".agents" / "skills" / "my-tool"
    assert agent_file.exists()
    assert rule_mdc.exists()
    assert skill_dir.exists()

    # Undo
    undo_res = undo_packs(
        home=fake_home, manifest_path=applied_manifest_path(aiwork_dir)
    )

    assert len(undo_res.removed) >= 5
    assert len(undo_res.modified) == 0
    assert not agent_file.exists()
    assert not rule_mdc.exists()
    assert not skill_dir.exists()  # Empty skill dir cleaned up

    manifest = load_manifest(home=aiwork_dir)
    assert len(manifest.entries) == 0


def test_undo_modified_file_not_deleted(tmp_path: Path):
    fake_home = tmp_path / "fake_home"
    aiwork_dir = tmp_path / ".aiwork"
    aiwork_dir.mkdir(parents=True, exist_ok=True)

    pack_dir = _create_sample_pack(tmp_path / "sample-pack")
    pack = validate_pack(pack_dir)

    apply_packs(
        packs=[pack],
        dry_run=False,
        replace=False,
        home=fake_home,
        manifest_path=applied_manifest_path(aiwork_dir),
    )

    agent_file = fake_home / ".agents" / "agents" / "builder.md"
    assert agent_file.exists()

    # Modify the agent file
    agent_file.write_text("# User hand-modified instructions\n", encoding="utf-8")

    # Undo
    undo_res = undo_packs(
        home=fake_home, manifest_path=applied_manifest_path(aiwork_dir)
    )

    # Modified file must NOT be deleted!
    assert str(agent_file) in undo_res.modified
    assert agent_file.exists()
    assert (
        agent_file.read_text(encoding="utf-8")
        == "# User hand-modified instructions\n"
    )

    # Manifest record should still be removed from tracking
    manifest = load_manifest(home=aiwork_dir)
    assert manifest.get(agent_file) is None


# =====================================================================
# 5. Kit Protection & nlink > 1 Protection
# =====================================================================


def test_protection_nlink_gt_1_always_rejected(tmp_path: Path):
    fake_home = tmp_path / "fake_home"
    aiwork_dir = tmp_path / ".aiwork"
    aiwork_dir.mkdir(parents=True, exist_ok=True)

    rules_dir = fake_home / ".agents" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    # Create an external kit hardlink pair (not in manifest)
    kit_rule_mdc = rules_dir / "00-identity.mdc"
    kit_rule_md = rules_dir / "00-identity.md"
    kit_rule_mdc.write_text("# Kit original canonical rule", encoding="utf-8")
    try:
        os.link(kit_rule_mdc, kit_rule_md)
    except OSError:
        pytest.skip("Filesystem does not support hardlinks in test environment")

    assert kit_rule_mdc.stat().st_nlink > 1

    pack_dir = _create_sample_pack(tmp_path / "sample-pack")
    pack = validate_pack(pack_dir)

    # Dry run should report conflict
    dry_res = apply_packs(
        packs=[pack],
        dry_run=True,
        replace=False,
        home=fake_home,
        manifest_path=applied_manifest_path(aiwork_dir),
    )
    conflicts = dry_res.plans["conflicts"]
    assert any("kit protection" in c["reason"].lower() for c in conflicts)

    # Real apply, EVEN WITH replace=True, MUST FAIL and raise PackError!
    with pytest.raises(PackError, match="kit protection"):
        apply_packs(
            packs=[pack],
            dry_run=False,
            replace=True,  # Even with replace=True, kit hardlinks are NEVER overwritten
            home=fake_home,
            manifest_path=applied_manifest_path(aiwork_dir),
        )

    # Content and inodes remain untouched
    assert kit_rule_mdc.read_text(encoding="utf-8") == "# Kit original canonical rule"
    assert os.path.samefile(kit_rule_mdc, kit_rule_md)


def test_replace_existing_file_with_backup_and_undo_restore(tmp_path: Path):
    fake_home = tmp_path / "fake_home"
    aiwork_dir = tmp_path / ".aiwork"
    aiwork_dir.mkdir(parents=True, exist_ok=True)

    agents_dir = fake_home / ".agents" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    custom_agent = agents_dir / "builder.md"
    custom_agent.write_text("# User initial single file", encoding="utf-8")

    pack_dir = _create_sample_pack(tmp_path / "sample-pack")
    pack = validate_pack(pack_dir)

    # Without replace=True, fails with conflict
    with pytest.raises(PackError, match="replace=False"):
        apply_packs(
            packs=[pack],
            dry_run=False,
            replace=False,
            home=fake_home,
            manifest_path=applied_manifest_path(aiwork_dir),
        )

    # With replace=True, succeeds and backs up
    apply_res = apply_packs(
        packs=[pack],
        dry_run=False,
        replace=True,
        home=fake_home,
        manifest_path=applied_manifest_path(aiwork_dir),
    )
    assert apply_res.success is True
    assert "Builder agent" in custom_agent.read_text(encoding="utf-8")

    manifest = load_manifest(home=aiwork_dir)
    entry = manifest.get(custom_agent)
    assert entry is not None
    assert entry.backup_path is not None
    assert Path(entry.backup_path).is_file()

    # When undo is called, user's original content is restored from backup!
    undo_res = undo_packs(
        home=fake_home, manifest_path=applied_manifest_path(aiwork_dir)
    )
    assert str(custom_agent) in undo_res.restored
    assert custom_agent.read_text(encoding="utf-8") == "# User initial single file"


# =====================================================================
# 6. Rollback on Failure Test
# =====================================================================


def test_rollback_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_home = tmp_path / "fake_home"
    aiwork_dir = tmp_path / ".aiwork"
    aiwork_dir.mkdir(parents=True, exist_ok=True)

    pack_dir = _create_sample_pack(tmp_path / "sample-pack")
    pack = validate_pack(pack_dir)

    # Simulate an error on writing the 3rd file
    original_replace = os.replace
    call_count = 0

    def fail_after_two(src, dst):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise OSError("Simulated disk error during apply")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_after_two)

    with pytest.raises(PackError, match="Apply failed and was rolled back"):
        apply_packs(
            packs=[pack],
            dry_run=False,
            replace=False,
            home=fake_home,
            manifest_path=applied_manifest_path(aiwork_dir),
        )

    # Verify all previously written files are cleaned up
    agent_file = fake_home / ".agents" / "agents" / "builder.md"
    assert not agent_file.exists()

    # Manifest should not contain entries
    manifest = load_manifest(home=aiwork_dir)
    assert len(manifest.entries) == 0


# =====================================================================
# 7. CLI Command Integration Tests
# =====================================================================


def test_cli_packs_workflow(tmp_path: Path):
    fake_home = tmp_path / "fake_home"
    aiwork_dir = tmp_path / ".aiwork"
    aiwork_dir.mkdir(parents=True, exist_ok=True)

    library_dir = aiwork_dir / "library"
    library_dir.mkdir(parents=True, exist_ok=True)

    pack_dir = _create_sample_pack(library_dir / "sample-pack")

    # 1. validate command
    val_res = runner.invoke(app, ["packs", "validate", str(pack_dir)])
    assert val_res.exit_code == 0
    assert "is valid" in val_res.output

    # 2. list command (initially disabled)
    list_res = runner.invoke(app, ["packs", "list"])
    assert list_res.exit_code == 0
    assert "sample-pack" in list_res.output
    assert "DISABLED" in list_res.output

    # 3. enable command
    en_res = runner.invoke(app, ["packs", "enable", "sample-pack"])
    assert en_res.exit_code == 0
    assert "enabled" in en_res.output

    list_res2 = runner.invoke(app, ["packs", "list"])
    assert "ENABLED" in list_res2.output

    # 4. status command before apply
    st_res = runner.invoke(app, ["packs", "status"])
    assert st_res.exit_code == 0
    assert "Machine:" in st_res.output
    assert "Applied entries: 0" in st_res.output

    # 5. doctor command
    doc_res = runner.invoke(app, ["packs", "doctor"])
    assert doc_res.exit_code == 0
    assert "Packs Environment & Health Check" in doc_res.output

    # 6. apply command --dry-run (default)
    apply_dry = runner.invoke(app, ["packs", "apply"])
    assert apply_dry.exit_code == 0
    assert "Dry Run Plan" in apply_dry.output
    assert "將新增" in apply_dry.output

    # 7. apply command --no-dry-run
    apply_real = runner.invoke(app, ["packs", "apply", "--no-dry-run"])
    assert apply_real.exit_code == 0
    assert "applied successfully" in apply_real.output

    # 8. status command after apply
    st_res2 = runner.invoke(app, ["packs", "status"])
    assert "Applied entries:" in st_res2.output
    assert "INTACT" in st_res2.output

    # 9. undo command
    undo_res = runner.invoke(app, ["packs", "undo"])
    assert undo_res.exit_code == 0
    assert "Packs Undo Summary" in undo_res.output
    assert "已刪除" in undo_res.output

    # 10. disable command
    dis_res = runner.invoke(app, ["packs", "disable", "sample-pack"])
    assert dis_res.exit_code == 0
    assert "disabled" in dis_res.output
