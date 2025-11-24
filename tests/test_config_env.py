import os
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from config import ConfigError, load_config


def clear_env(monkeypatch):
    for key in list(os.environ.keys()):
        if key.startswith("FIRESTICK_MINDER_DEVICE_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("RUNNER_DEVICES", raising=False)
    monkeypatch.delenv("FIRESTICK_MINDER_CONFIG", raising=False)
    monkeypatch.delenv("MINDER_APP", raising=False)
    monkeypatch.delenv("RUNNER_APP", raising=False)


def test_structured_env_devices(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("FIRESTICK_MINDER_DEVICE_LR_HOST", "192.168.30.51")
    monkeypatch.setenv("FIRESTICK_MINDER_DEVICE_LR_APP", "com.snapwood.nfolio")
    monkeypatch.setenv("FIRESTICK_MINDER_DEVICE_LR_ADB_PORT", "5555")

    cfg = load_config()

    assert cfg["devices"]
    device = cfg["devices"][0]
    assert device["name"] == "LR"
    assert device["host"] == "192.168.30.51"
    assert device["adb_port"] == 5555
    assert device["slideshow_component"] == "com.snapwood.nfolio"


def test_runner_devices_fallback(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("RUNNER_DEVICES", "LR=192.168.30.51:5555")
    monkeypatch.setenv("MINDER_APP", "com.snapwood.nfolio")

    cfg = load_config()

    device = cfg["devices"][0]
    assert device["name"] == "LR"
    assert device["host"] == "192.168.30.51"
    assert device["adb_port"] == 5555
    assert device["slideshow_component"] == "com.snapwood.nfolio"


def test_no_devices_raises(monkeypatch):
    clear_env(monkeypatch)

    with pytest.raises(ConfigError) as excinfo:
        load_config()

    assert "no devices configured" in str(excinfo.value)
