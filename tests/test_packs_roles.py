from __future__ import annotations

import json
import os
from pathlib import Path
import pytest
from typer.testing import CliRunner

from aiwork.cli import app
from aiwork.packs import (
    RoleDef,
    check_role_skills,
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
    load_machine_profile,
    save_machine_profile,
    MachineProfile,
)

runner = CliRunner()


# =====================================================================
# 1. Role Definition Parsing & Validation
# =====================================================================


def test_parse_role_def_basic():
    content = """---
name: builder
description: Handles coding, implementation, and test verification
skills:
  - tdd
  - webapp-testing
---
# Principles
1. Follow sealed plans.
2. Verify before complete.
"""
    role = parse_role_def(content)
    assert role.name == "builder"
    assert role.description == "Handles coding, implementation, and test verification"
    assert role.skills == ["tdd", "webapp-testing"]
    assert "# Principles" in role.body
    assert "Verify before complete." in role.body


def test_parse_role_def_optional_skills_and_empty_body():
    content = """---
name: writer
description: Refines documentation and creates clear diffs
---
"""
    role = parse_role_def(content)
    assert role.name == "writer"
    assert role.description == "Refines documentation and creates clear diffs"
    assert role.skills == []
    assert role.body == ""


def test_parse_role_def_with_colons():
    content = """---
name: planner
description: "Breaks tasks into sealed plans: contracts, boundaries, and acceptance"
skills:
  - planseal
---
Plan principles.
"""
    role = parse_role_def(content)
    assert role.name == "planner"
    assert "sealed plans: contracts" in role.description


def test_parse_role_def_invalid_frontmatter():
    # Missing frontmatter
    with pytest.raises(ValueError, match="missing YAML frontmatter"):
        parse_role_def("Just markdown without frontmatter")

    # Frontmatter not a dict
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        parse_role_def("---\n- just a list\n---\nBody")

    # Invalid name
    with pytest.raises(ValueError, match="missing or invalid 'name'"):
        parse_role_def("---\ndescription: ok\n---\n")

    with pytest.raises(ValueError, match="Invalid role name 'BUILDER'"):
        parse_role_def("---\nname: BUILDER\ndescription: ok\n---\n")

    with pytest.raises(ValueError, match="Invalid role name '1builder'"):
        parse_role_def("---\nname: 1builder\ndescription: ok\n---\n")

    with pytest.raises(ValueError, match="Invalid role name 'builder_und'"):
        parse_role_def("---\nname: builder_und\ndescription: ok\n---\n")

    # Missing description
    with pytest.raises(ValueError, match="missing or empty 'description'"):
        parse_role_def("---\nname: builder\n---\n")

    with pytest.raises(ValueError, match="missing or empty 'description'"):
        parse_role_def("---\nname: builder\ndescription: '   '\n---\n")

    # Invalid skills
    with pytest.raises(ValueError, match="'skills' must be a list of strings"):
        parse_role_def("---\nname: builder\ndescription: ok\nskills: not-a-list\n---\n")

    with pytest.raises(ValueError, match="'skills' must be a list of strings"):
        parse_role_def("---\nname: builder\ndescription: ok\nskills: [123, 'tdd']\n---\n")


# =====================================================================
# 2. Role Definition Serialization & Safe Quoting
# =====================================================================


def test_serialize_role_def_with_colons():
    # agy requires strings with colons in frontmatter to be quoted
    role = RoleDef(
        name="builder",
        description="Handles coding: implementation, verification: steps 1, 2",
        skills=["webapp-testing", "test:colon"],
        body="# Work Principles\nDo not guess.",
    )
    serialized = serialize_role_def(role)
    assert 'description: "Handles coding: implementation, verification: steps 1, 2"' in serialized
    assert '- "test:colon"' in serialized

    # Roundtrip check
    parsed = parse_role_def(serialized)
    assert parsed.name == role.name
    assert parsed.description == role.description
    assert parsed.skills == role.skills
    assert parsed.body == role.body


def test_serialize_role_def_no_colon_and_no_skills():
    role = RoleDef(
        name="writer",
        description="Simple writer description without colons",
        skills=[],
        body="Body text only",
    )
    serialized = serialize_role_def(role)
    assert "name: writer" in serialized
    assert "description: Simple writer description without colons" in serialized
    # Optional skills omitted when empty
    assert "skills:" not in serialized

    parsed = parse_role_def(serialized)
    assert parsed.name == "writer"
    assert parsed.description == "Simple writer description without colons"
    assert parsed.skills == []
    assert parsed.body == "Body text only"


def test_load_and_save_role_def(tmp_path: Path):
    role_file = tmp_path / "agents" / "builder.md"
    role = RoleDef(
        name="builder",
        description="Coding: building features",
        skills=["tdd"],
        body="Work strictly according to sealed plans.",
    )
    saved_path = save_role_def(role, role_file)
    assert saved_path == role_file
    assert role_file.is_file()

    loaded = load_role_def(role_file)
    assert loaded.name == role.name
    assert loaded.description == role.description
    assert loaded.skills == role.skills
    assert loaded.body == role.body


def test_save_role_def_missing_skills_does_not_block(tmp_path: Path):
    role_file = tmp_path / "agents" / "builder.md"
    role = RoleDef(
        name="builder",
        description="Builder role",
        skills=["nonexistent-skill"],
        body="Instructions",
    )
    # Provided pool doesn't have the skill; save_role_def must not raise
    saved = save_role_def(role, role_file, pool={"tdd": {"source": "external"}})
    assert saved.is_file()
    assert load_role_def(saved).skills == ["nonexistent-skill"]


# =====================================================================
# 3. Skills Pool Scanning & Missing Skills Detection
# =====================================================================


def test_scan_skills_pool_empty(tmp_path: Path):
    home = tmp_path / ".aiwork"
    home.mkdir(parents=True, exist_ok=True)
    user_h = tmp_path / "user"
    user_h.mkdir(parents=True, exist_ok=True)
    profile = MachineProfile(
        cli_dirs={"agents": str(user_h / ".agents")},
        libraries=[str(home / "library")],
        enabled_packs=[],
    )
    pool = scan_skills_pool(home=home, profile=profile)
    assert pool == {}


def test_scan_skills_pool_external_and_packs(tmp_path: Path):
    home = tmp_path / ".aiwork"
    user_h = tmp_path / "user"
    agents_dir = user_h / ".agents"
    agents_skills = agents_dir / "skills"
    agents_skills.mkdir(parents=True)

    # 1. External skill
    ext_skill = agents_skills / "webapp-testing"
    ext_skill.mkdir()
    (ext_skill / "SKILL.md").write_text(
        """---
name: webapp-testing
description: Playwright based web testing toolkit
---
# Webapp Testing
""",
        encoding="utf-8",
    )

    # 2. Pack skill
    library_dir = home / "library"
    pack_dir = library_dir / "pack-core"
    pack_dir.mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        """id: pack-core
name: pack-core
description: Core pack
""",
        encoding="utf-8",
    )
    pack_skills = pack_dir / "skills" / "tdd"
    pack_skills.mkdir(parents=True)
    (pack_skills / "SKILL.md").write_text(
        """---
name: tdd
description: Test-driven development workflow
---
# TDD
""",
        encoding="utf-8",
    )

    profile = MachineProfile(
        cli_dirs={"agents": str(agents_dir)},
        libraries=[str(library_dir)],
        enabled_packs=["pack-core"],
    )

    pool = scan_skills_pool(home=home, profile=profile)

    assert "webapp-testing" in pool
    assert pool["webapp-testing"]["source"] == "external"
    assert "Playwright based" in pool["webapp-testing"]["description"]

    assert "tdd" in pool
    assert pool["tdd"]["source"] == "pack:pack-core"
    assert "Test-driven development" in pool["tdd"]["description"]


def test_check_role_skills_and_missing_skills():
    pool = {
        "tdd": {
            "name": "tdd",
            "description": "TDD workflow",
            "source": "external",
        },
        "frontend-design": {
            "name": "frontend-design",
            "description": "UI guidelines",
            "source": "pack:design-pack",
        },
    }

    role_skills = ["tdd", "frontend-design", "ui-ux-pro-max", "missing-tool"]
    missing = get_missing_skills(role_skills, pool)
    assert missing == ["ui-ux-pro-max", "missing-tool"]

    status = check_role_skills(role_skills, pool)
    assert status["tdd"]["available"] is True
    assert status["tdd"]["status"] == "ok"
    assert status["tdd"]["source"] == "external"

    assert status["frontend-design"]["available"] is True
    assert status["frontend-design"]["status"] == "ok"
    assert status["frontend-design"]["source"] == "pack:design-pack"

    assert status["ui-ux-pro-max"]["available"] is False
    assert status["ui-ux-pro-max"]["status"] == "缺"
    assert status["ui-ux-pro-max"]["source"] is None

    assert status["missing-tool"]["available"] is False
    assert status["missing-tool"]["status"] == "缺"

    role = RoleDef(name="builder", description="Builder", skills=role_skills)
    assert role.get_missing_skills(pool) == ["ui-ux-pro-max", "missing-tool"]
    assert role.check_skills(pool)["ui-ux-pro-max"]["status"] == "缺"


# =====================================================================
# 4. Delivery Status & Path Validation
# =====================================================================


def test_is_valid_role_path():
    assert is_valid_role_path("C:/Users/<user>/.agents/agents/builder.md")
    assert is_valid_role_path("/home/user/.agents/agents/builder.md")
    assert is_valid_role_path("C:/valid_path-1.0/agents/writer.md")

    # Invalid characters: space, unicode/chinese
    assert not is_valid_role_path("C:/Users/<user> Chen/.agents/agents/builder.md")
    assert not is_valid_role_path("C:/path/to/projects/.agents/agents/builder.md")


def test_get_role_delivery_status(tmp_path: Path):
    # None
    defined, delivery = get_role_delivery_status(None)
    assert defined == "no"
    assert delivery == "none"

    # Nonexistent file
    defined, delivery = get_role_delivery_status(tmp_path / "nonexistent.md")
    assert defined == "no"
    assert delivery == "none"

    # Valid path
    valid_file = tmp_path / "builder.md"
    valid_file.write_text("content", encoding="utf-8")
    defined, delivery = get_role_delivery_status(valid_file)
    assert defined == valid_file.resolve().as_posix()
    if is_valid_role_path(valid_file):
        assert delivery == "prompt-path"
    else:
        assert delivery == "none"

    # Invalid path with space
    dir_with_space = tmp_path / "path with space"
    dir_with_space.mkdir()
    spaced_file = dir_with_space / "builder.md"
    spaced_file.write_text("content", encoding="utf-8")
    defined, delivery = get_role_delivery_status(spaced_file)
    assert defined == spaced_file.resolve().as_posix()
    assert delivery == "none"


# =====================================================================
# 5. aiwork roles CLI Defined & Delivery Fields
# =====================================================================


def test_aiwork_roles_undefined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        """
version: 1
roles:
  builder:
    agent: gemini
    model: gemini-3.8-flash-high
    description: good builder
""",
        encoding="utf-8",
    )
    models_file = tmp_path / "models.yaml"
    models_file.write_text(
        """
version: 1
models:
  gemini:
    - id: gemini-3.8-flash-high
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))

    # Text output check
    res = runner.invoke(app, ["roles"])
    assert res.exit_code == 0
    assert "Defined: no" in res.stdout
    assert "Delivery: none" in res.stdout

    # JSON output check
    res_json = runner.invoke(app, ["roles", "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    builder_role = data["roles"]["builder"]
    assert builder_role["defined"] == "no"
    assert builder_role["delivery"] == "none"


def test_aiwork_roles_defined_in_agents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        """
version: 1
roles:
  builder:
    agent: gemini
    model: gemini-3.8-flash-high
    description: good builder
""",
        encoding="utf-8",
    )
    models_file = tmp_path / "models.yaml"
    models_file.write_text(
        """
version: 1
models:
  gemini:
    - id: gemini-3.8-flash-high
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))

    user_home = tmp_path / "user_home"
    agents_dir = user_home / ".agents" / "agents"
    agents_dir.mkdir(parents=True)
    builder_md = agents_dir / "builder.md"
    builder_md.write_text(
        """---
name: builder
description: good builder
---
Follow instructions.
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_USER_HOME", str(user_home))

    # Update machine profile cli_dirs
    profile = MachineProfile(cli_dirs={"agents": str(user_home / ".agents")})
    save_machine_profile(profile, home=tmp_path / ".aiwork")

    res = runner.invoke(app, ["roles"])
    assert res.exit_code == 0
    posix_path = builder_md.resolve().as_posix()
    assert f"Defined: {posix_path}" in res.stdout
    if is_valid_role_path(builder_md):
        assert "Delivery: prompt-path" in res.stdout
    else:
        assert "Delivery: none" in res.stdout

    res_json = runner.invoke(app, ["roles", "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert data["roles"]["builder"]["defined"] == posix_path
    if is_valid_role_path(builder_md):
        assert data["roles"]["builder"]["delivery"] == "prompt-path"
    else:
        assert data["roles"]["builder"]["delivery"] == "none"


def test_aiwork_roles_defined_in_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        """
version: 1
roles:
  writer:
    agent: cursor
    model: composer-2.5
    description: good writer
""",
        encoding="utf-8",
    )
    models_file = tmp_path / "models.yaml"
    models_file.write_text(
        """
version: 1
models:
  cursor:
    - id: composer-2.5
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))

    # Create pack in library
    library_dir = tmp_path / "library"
    pack_dir = library_dir / "pack-writing"
    (pack_dir / "agents").mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        """id: pack-writing
name: pack-writing
description: Writing pack
""",
        encoding="utf-8",
    )
    writer_md = pack_dir / "agents" / "writer.md"
    writer_md.write_text(
        """---
name: writer
description: good writer
---
Writing principles.
""",
        encoding="utf-8",
    )

    profile = MachineProfile(
        libraries=[str(library_dir)],
        enabled_packs=["pack-writing"],
    )
    save_machine_profile(profile, home=tmp_path / ".aiwork")

    res = runner.invoke(app, ["roles"])
    assert res.exit_code == 0
    posix_path = writer_md.resolve().as_posix()
    assert f"Defined: {posix_path}" in res.stdout

    res_json = runner.invoke(app, ["roles", "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert data["roles"]["writer"]["defined"] == posix_path
