import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

ENV_CONFIG_VAR = "FIRESTICK_MINDER_CONFIG"


logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised for configuration-related issues."""


_DEF_HOME_PACKAGES = {"com.amazon.tv.launcher", "com.amazon.firetv.launcher"}


def _parse_bool_env(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    value_lower = value.strip().lower()
    if value_lower in {"1", "true", "yes", "on"}:
        return True
    if value_lower in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(
        "Boolean env vars must be one of: 1, 0, true, false, yes, no, on, off"
    )


def _parse_int_env(value: Optional[str], var_name: str) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{var_name} must be an integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{var_name} must be a positive integer")
    return parsed


def _normalize_device(device: Dict[str, Any], idx: int) -> Dict[str, Any]:
    name = device.get("name") or f"device_{idx}"
    host = device.get("host")
    home_packages = device.get("home_packages", []) or list(_DEF_HOME_PACKAGES)
    slideshow_component = device.get("slideshow_component")

    if not host or not isinstance(host, (str, int)):
        raise ConfigError(f"Device {name!r} is missing a valid 'host' field")

    if not slideshow_component or not isinstance(slideshow_component, str):
        raise ConfigError(f"Device {name!r} is missing 'slideshow_component'")

    if not isinstance(home_packages, list) or not home_packages:
        raise ConfigError(
            f"Device {name!r} must have a non-empty 'home_packages' list"
        )

    return {
        "name": str(name),
        "host": str(host),
        "home_packages": set(map(str, home_packages)),
        "slideshow_component": slideshow_component,
    }


def _normalize_mqtt(mqtt_cfg: Dict[str, Any]) -> Dict[str, Any]:
    host = mqtt_cfg.get("host")
    port = mqtt_cfg.get("port", 1883)
    topic_prefix = mqtt_cfg.get("topic_prefix", "home/firestick")

    if not host or not isinstance(host, str):
        raise ConfigError("mqtt.host must be a non-empty string")

    if not isinstance(port, int) or port <= 0:
        raise ConfigError("mqtt.port must be a positive integer")

    if not isinstance(topic_prefix, str) or not topic_prefix:
        raise ConfigError("mqtt.topic_prefix must be a non-empty string")

    return {
        "host": host,
        "port": port,
        "topic_prefix": topic_prefix.rstrip("/"),
        "username": mqtt_cfg.get("username"),
        "password": mqtt_cfg.get("password"),
    }


def load_env_devices() -> List[Dict[str, Any]]:
    """Build a list of device configs from indexed environment variables."""

    pattern_fsm = re.compile(r"^FSM_DEVICE_(\d+)_([A-Z_]+)$")
    pattern_runner = re.compile(r"^RUNNER_DEVICE_(\d+)_([A-Z_]+)$")
    devices_raw: Dict[int, Dict[str, str]] = {}

    def _apply_device_field(idx: int, field: str, value: str) -> None:
        devices_raw.setdefault(idx, {})
        if field in {"HOST", "IP"}:
            devices_raw[idx]["host"] = value
        elif field == "NAME":
            devices_raw[idx]["name"] = value
        elif field == "IDLE_APP":
            devices_raw[idx]["slideshow_component"] = value

    for key, value in os.environ.items():
        match = pattern_fsm.match(key)
        if match:
            _apply_device_field(int(match.group(1)), match.group(2), value)
            continue

        runner_match = pattern_runner.match(key)
        if runner_match:
            _apply_device_field(int(runner_match.group(1)), runner_match.group(2), value)

    devices: List[Dict[str, Any]] = []
    for idx in sorted(devices_raw):
        raw = devices_raw[idx]
        if not raw:
            continue
        if "host" not in raw or "slideshow_component" not in raw:
            raise ConfigError(
                "Env devices require HOST and IDLE_APP (slideshow_component) entries"
            )

        normalized = _normalize_device(raw, idx)
        if "name" not in raw:
            normalized["name"] = f"device_{idx}"
        devices.append(normalized)

    return devices


def _first_runner_device_idle_timeout() -> Tuple[Optional[str], str]:
    pattern = re.compile(r"^RUNNER_DEVICE_(\d+)_IDLE_TIMEOUT$")
    first_match: Optional[int] = None
    first_value: Optional[str] = None

    for key, value in os.environ.items():
        match = pattern.match(key)
        if not match:
            continue

        idx = int(match.group(1))
        if first_match is None or idx < first_match:
            first_match = idx
            first_value = value

    if first_match is None:
        return None, "FSM_IDLE_TIMEOUT"

    return first_value, f"RUNNER_DEVICE_{first_match}_IDLE_TIMEOUT"


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from optional YAML file plus environment.
    If FIRESTICK_MINDER_CONFIG is unset, missing, or points to a directory,
    we fall back to env-only mode instead of raising.
    """

    config_path_env = path or os.getenv(ENV_CONFIG_VAR)

    if not config_path_env:
        logger.info("No FIRESTICK_MINDER_CONFIG set; using env-only configuration")
        return build_config_from_env_only()

    config_path = Path(config_path_env)

    if config_path.is_dir():
        logger.warning(
            "Config path %s is a directory; ignoring YAML and using env-only configuration",
            config_path,
        )
        return build_config_from_env_only()

    if not config_path.exists():
        logger.warning(
            "Config file %s not found; using env-only configuration",
            config_path,
        )
        return build_config_from_env_only()

    if not config_path.is_file():
        raise ConfigError(f"Config path {config_path} is not a regular file")

    yaml_config: Dict[str, Any] = {}
    with config_path.open("r", encoding="utf-8") as f:
        try:
            yaml_config = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Failed to parse YAML config: {exc}") from exc

    if not isinstance(yaml_config, dict):
        raise ConfigError("Top-level YAML config must be a mapping")

    return build_config_from_yaml_and_env(yaml_config, config_path)


def build_config_from_env_only() -> Dict[str, Any]:
    return _build_config({}, yaml_loaded=False, config_path=None)


def build_config_from_yaml_and_env(
    yaml_config: Dict[str, Any], config_path: Optional[Path] = None
) -> Dict[str, Any]:
    return _build_config(yaml_config, yaml_loaded=True, config_path=config_path)


def _build_config(
    yaml_config: Dict[str, Any], yaml_loaded: bool, config_path: Optional[Path]
) -> Dict[str, Any]:
    """Build the configuration object from YAML and environment data."""
    env_devices = load_env_devices()
    env_overrides_used = False

    sources: Dict[str, str] = {}

    idle_app = None
    idle_app_source = "default"

    yaml_idle_app = yaml_config.get("idle_app") or yaml_config.get("app")
    if yaml_idle_app is not None:
        if not isinstance(yaml_idle_app, str) or not yaml_idle_app.strip():
            raise ConfigError("idle_app/app must be a non-empty string if provided")
        idle_app = yaml_idle_app.strip()
        idle_app_source = "yaml"

    env_idle_app = os.getenv("RUNNER_APP")
    if env_idle_app:
        idle_app = env_idle_app
        idle_app_source = "env"
        env_overrides_used = True
        print(f"[config] idle app set from env RUNNER_APP={env_idle_app}")
    elif idle_app is not None:
        print(f"[config] idle app set from YAML: {idle_app}")

    # poll_interval_seconds
    poll_interval = 5
    if "poll_interval_seconds" in yaml_config:
        poll_interval = yaml_config.get("poll_interval_seconds", 5)
        if not isinstance(poll_interval, int) or poll_interval <= 0:
            raise ConfigError("poll_interval_seconds must be a positive integer")
        sources["poll_interval_seconds"] = "yaml"
    env_poll_interval_value = os.environ.get("FSM_POLL_INTERVAL")
    poll_interval_var_name = "FSM_POLL_INTERVAL"
    if env_poll_interval_value is None:
        env_poll_interval_value = os.environ.get("RUNNER_POLL_SECONDS")
        if env_poll_interval_value is not None:
            poll_interval_var_name = "RUNNER_POLL_SECONDS"

    env_poll_interval = _parse_int_env(env_poll_interval_value, poll_interval_var_name)
    if env_poll_interval is not None:
        poll_interval = env_poll_interval
        env_overrides_used = True
        sources["poll_interval_seconds"] = "env"
    elif "poll_interval_seconds" not in sources:
        sources["poll_interval_seconds"] = "default"

    # idle_timeout_seconds
    idle_timeout = None
    if "idle_timeout_seconds" in yaml_config:
        idle_timeout = yaml_config.get("idle_timeout_seconds")
        if idle_timeout is not None:
            if not isinstance(idle_timeout, int) or idle_timeout <= 0:
                raise ConfigError(
                    "idle_timeout_seconds, if set, must be a positive integer"
                )
            sources["idle_timeout_seconds"] = "yaml"
    env_idle_timeout_value = os.environ.get("FSM_IDLE_TIMEOUT")
    idle_timeout_var_name = "FSM_IDLE_TIMEOUT"
    if env_idle_timeout_value is None:
        env_idle_timeout_value = os.environ.get("RUNNER_IDLE_TIMEOUT")
        if env_idle_timeout_value is not None:
            idle_timeout_var_name = "RUNNER_IDLE_TIMEOUT"
    if env_idle_timeout_value is None:
        env_idle_timeout_value, idle_timeout_var_name = _first_runner_device_idle_timeout()

    if env_idle_timeout_value is not None:
        idle_timeout_parsed = _parse_int_env(env_idle_timeout_value, idle_timeout_var_name)
        idle_timeout = idle_timeout_parsed
        env_overrides_used = True
        sources["idle_timeout_seconds"] = "env"
    elif "idle_timeout_seconds" not in sources:
        sources["idle_timeout_seconds"] = "default"

    log_level = str(yaml_config.get("log_level", "info")) if yaml_loaded else "info"
    if "FSM_LOG_LEVEL" in os.environ:
        log_level = os.environ.get("FSM_LOG_LEVEL", log_level)
        env_overrides_used = True
        sources["log_level"] = "env"
    else:
        sources["log_level"] = "yaml" if yaml_loaded and "log_level" in yaml_config else "default"

    # Devices
    devices_config = yaml_config.get("devices", []) if yaml_loaded else []
    devices: List[Dict[str, Any]] = []
    if env_devices:
        devices = env_devices
        sources["devices"] = "env"
        env_overrides_used = True
    else:
        if not isinstance(devices_config, list) or not devices_config:
            raise ConfigError("devices must be a non-empty list")
        for idx, dev in enumerate(devices_config):
            if not isinstance(dev, dict):
                raise ConfigError(f"Device entry at index {idx} must be a mapping")
            devices.append(_normalize_device(dev, idx))
        sources["devices"] = "yaml"

    if idle_app:
        for device in devices:
            device["slideshow_component"] = idle_app

    sources["idle_app"] = idle_app_source

    # MQTT
    mqtt_cfg = None
    mqtt_source = "default"
    if yaml_loaded and yaml_config.get("mqtt") is not None:
        yaml_mqtt = yaml_config.get("mqtt")
        if not isinstance(yaml_mqtt, dict):
            raise ConfigError("mqtt section must be a mapping if present")
        mqtt_cfg = _normalize_mqtt(yaml_mqtt)
        mqtt_source = "yaml"

    env_mqtt_enabled = _parse_bool_env(os.environ.get("FSM_MQTT_ENABLED"))
    env_mqtt_host = os.environ.get("FSM_MQTT_HOST")
    env_mqtt_port = _parse_int_env(os.environ.get("FSM_MQTT_PORT"), "FSM_MQTT_PORT")
    env_mqtt_topic_prefix = os.environ.get("FSM_MQTT_TOPIC_PREFIX")

    env_mqtt_fields_set = any(
        val is not None
        for val in (env_mqtt_enabled, env_mqtt_host, env_mqtt_port, env_mqtt_topic_prefix)
    )

    if env_mqtt_fields_set:
        env_overrides_used = True

    if env_mqtt_enabled is False:
        mqtt_cfg = None
        mqtt_source = "env_disabled"
    else:
        if env_mqtt_enabled is True or env_mqtt_host or env_mqtt_port or env_mqtt_topic_prefix:
            mqtt_cfg = mqtt_cfg or {}
            if env_mqtt_host:
                mqtt_cfg["host"] = env_mqtt_host
            if env_mqtt_port is not None:
                mqtt_cfg["port"] = env_mqtt_port
            if env_mqtt_topic_prefix:
                mqtt_cfg["topic_prefix"] = env_mqtt_topic_prefix
            mqtt_cfg = _normalize_mqtt(mqtt_cfg)
            mqtt_source = "env"
        elif mqtt_cfg is not None:
            mqtt_cfg = _normalize_mqtt(mqtt_cfg)

    sources["mqtt"] = mqtt_source

    env_present = env_overrides_used or bool(env_devices)

    # Log sources
    poll_src = sources.get("poll_interval_seconds", "unknown")
    idle_src = sources.get("idle_timeout_seconds", "unknown")
    devices_src = sources.get("devices", "unknown")
    mqtt_src = sources.get("mqtt", "default")
    log_level_src = sources.get("log_level", "default")

    config_origin: List[str] = []
    if yaml_loaded:
        config_origin.append("YAML")
    if env_present:
        config_origin.append("environment")
    if not config_origin:
        config_origin.append("defaults")

    print(
        f"[config] Sources used: {', '.join(config_origin)}; "
        f"poll_interval_seconds ({poll_interval}) from {poll_src}; "
        f"idle_timeout_seconds ({idle_timeout}) from {idle_src}; "
        f"devices from {devices_src}; mqtt from {mqtt_src}; log_level from {log_level_src}."
    )

    return {
        "poll_interval_seconds": poll_interval,
        "idle_timeout_seconds": idle_timeout,
        "devices": devices,
        "mqtt": mqtt_cfg,
        "config_path": str(config_path) if yaml_loaded and config_path else None,
        "sources": sources,
        "env_devices_count": len(env_devices),
        "env_present": env_present,
        "log_level": log_level,
        "idle_app": idle_app,
        "idle_app_source": idle_app_source,
    }
