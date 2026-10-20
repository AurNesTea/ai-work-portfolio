"""Keep pytest off the long-term usage database."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_usage_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "usage.sqlite"
    monkeypatch.setenv("AIWORK_USAGE_DB", str(path))
    return path


@pytest.fixture(autouse=True)
def isolated_aiwork_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".aiwork"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AIWORK_HOME", str(home))
    user_home = tmp_path / "fake_user_home"
    user_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AIWORK_USER_HOME", str(user_home))
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    return home

