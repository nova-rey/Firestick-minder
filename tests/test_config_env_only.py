import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from config import load_config


def _set_basic_env(monkeypatch) -> None:
    monkeypatch.setenv("RUNNER_DEVICE_1_IP", "192.0.2.10")
    monkeypatch.setenv("RUNNER_DEVICE_1_IDLE_APP", "com.example/.MainActivity")


def test_load_config_env_only_when_path_unset(monkeypatch):
    monkeypatch.delenv("FIRESTICK_MINDER_CONFIG", raising=False)
    _set_basic_env(monkeypatch)

    cfg = load_config()

    assert cfg
    assert cfg.get("config_path") is None
    assert len(cfg.get("devices", [])) == 1


def test_load_config_env_only_when_file_missing(tmp_path: Path, monkeypatch):
    missing = tmp_path / "does_not_exist.yml"
    monkeypatch.setenv("FIRESTICK_MINDER_CONFIG", str(missing))
    _set_basic_env(monkeypatch)

    cfg = load_config()

    assert cfg
    assert cfg.get("config_path") is None
    assert len(cfg.get("devices", [])) == 1


def test_load_config_env_only_when_path_is_directory(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "configdir"
    config_dir.mkdir()
    monkeypatch.setenv("FIRESTICK_MINDER_CONFIG", str(config_dir))
    _set_basic_env(monkeypatch)

    cfg = load_config()

    assert cfg
    assert cfg.get("config_path") is None
    assert len(cfg.get("devices", [])) == 1
