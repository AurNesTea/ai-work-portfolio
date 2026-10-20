import json
import os
import shutil
from pathlib import Path
import pytest
from typer.testing import CliRunner

from aiwork.cli import app


runner = CliRunner()


def test_aiwork_roles_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        """
version: 1
roles:
  builder:
    agent: gemini
    model: gemini-3.8-flash-high
    effort: high
    description: good builder
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
  gemini:
    - id: gemini-3.8-flash-high
  cursor:
    - id: composer-2.5
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_ROLES", str(roles_file))
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))

    result = runner.invoke(app, ["roles"])
    assert result.exit_code == 0
    assert str(roles_file) in result.stdout
    assert "builder" in result.stdout
    assert "gemini-3.8-flash-high" in result.stdout
    assert "writer" in result.stdout
    assert "composer-2.5" in result.stdout


def test_aiwork_roles_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    result = runner.invoke(app, ["roles", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "tables" in data
    assert "roles" in data
    assert "builder" in data["roles"]
    assert data["roles"]["builder"]["agent"] == "gemini"
    assert data["roles"]["builder"]["model"] == "gemini-3.8-flash-high"


def test_aiwork_roles_check_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    result = runner.invoke(app, ["roles", "--check"])
    assert result.exit_code == 0
    assert "ok" in result.stdout.lower() or "check passed" in result.stdout.lower() or "成功" in result.stdout


def test_aiwork_roles_check_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    roles_file = tmp_path / "roles.yaml"
    roles_file.write_text(
        """
version: 1
roles:
  builder:
    agent: gemini
    model: unknown-model-xyz
    description: bad model
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

    result = runner.invoke(app, ["roles", "--check"])
    assert result.exit_code == 1
    assert "unknown-model-xyz" in result.stdout or "unknown-model-xyz" in result.stderr


def test_aiwork_models_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    models_file = tmp_path / "models.yaml"
    models_file.write_text(
        """
version: 1
models:
  cursor:
    - id: composer-2.5
  claude:
    - id: claude-opus-5-5
      note: 未驗證
  gemini:
    - id: gemini-3.8-flash-high
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))

    result = runner.invoke(app, ["models"])
    assert result.exit_code == 0
    assert "composer-2.5" in result.stdout
    assert "claude-opus-5-5" in result.stdout
    assert "gemini-3.8-flash-high" in result.stdout


def test_aiwork_models_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from unittest.mock import patch

    models_file = tmp_path / "models.yaml"
    models_file.write_text(
        """
version: 1
models:
  cursor:
    - id: composer-2.5
    - id: old-model
  claude:
    - id: claude-opus-5-5
  gemini:
    - id: gemini-3.8-flash-high
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWORK_MODELS", str(models_file))

    def fake_live_models(agent: str):
        if agent == "cursor":
            return ["composer-2.5", "new-model"], None
        if agent == "gemini":
            return ["gemini-3.8-flash-high"], None
        if agent == "claude":
            return None, "沒有列模型的指令"
        return None, "unknown"

    with patch("aiwork.dispatch.fetch_cli_models", side_effect=fake_live_models):
        result = runner.invoke(app, ["models", "--check"])
        assert result.exit_code == 0
        assert "沒有列模型的指令" in result.stdout
        assert "new-model" in result.stdout
        assert "old-model" in result.stdout


def test_aiwork_rules_path():
    result = runner.invoke(app, ["rules-path"])
    assert result.exit_code == 0
    path_str = result.stdout.strip()
    p = Path(path_str)
    assert p.is_file()
    assert "dispatch-rules.md" in p.name
    content = p.read_text(encoding="utf-8")
    assert "aiwork roles" in content
    assert "role:" in content

