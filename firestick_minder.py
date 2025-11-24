#!/usr/bin/env python3
"""
firestick-minder

A tiny daemon that watches one or more Fire TV / Firestick devices over ADB.
If a device is idle (by policy) and not currently playing media, firestick-minder
automatically launches a configured "idle target" app (e.g., slideshow, black-screen app,
or any other screensaver-style app).

Configuration is provided via environment variables, with an optional YAML file
for overrides when desired. YAML fields include:
- poll_interval_seconds
- optional idle_timeout_seconds
- devices: list of {name, host, home_packages, slideshow_component}
- optional mqtt: host/port/topic_prefix (+ optional username/password)

Environment variables can override or replace YAML values entirely when running
in containerized or managed environments.

Non-destructive:
- No rooting, no custom ROM, no launcher patching.
- Stop the script/container and your Firesticks go back to normal behavior.
"""

import json
import shutil
import subprocess
import time
import re
import sys
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

from config import ConfigError, load_config

try:
    import paho.mqtt.client as mqtt  # type: ignore
except ImportError:
    mqtt = None  # MQTT is optional; only used if configured


# ---------------------------------------------------------------------------
# ADB HELPERS
# ---------------------------------------------------------------------------


def ensure_adb_available() -> None:
    """
    Verify that the 'adb' binary is available on PATH.

    This is primarily a Docker-image sanity check so users get a clean
    error instead of [Errno 2] when adb is missing.
    """
    from logging import getLogger

    logger = getLogger("firestick_minder.adb_check")
    adb_path = shutil.which("adb")

    if not adb_path:
        logger.error(
            "[fatal] adb binary not found on PATH; this image is missing the "
            "'adb' package. Exiting."
        )
        sys.exit(1)

    logger.info("[startup] adb found at %s", adb_path)

def adb(device: Dict[str, Any], *args: str, timeout: int = 5) -> Optional[subprocess.CompletedProcess]:
    """
    Run an adb command against a specific Firestick and return the CompletedProcess.
    """
    adb_port = device.get("adb_port", 5555)
    target = f"{device['host']}:{adb_port}"
    cmd = ["adb", "-s", target, *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc
    except subprocess.TimeoutExpired:
        print(f"[{device['name']}] ADB command timed out: {' '.join(cmd)}", file=sys.stderr)
        return None


def ensure_connected(device: Dict[str, Any]) -> bool:
    """
    Make sure we're connected to this Firestick over TCP.
    If not, try to connect.
    """
    adb_port = device.get("adb_port", 5555)
    target = f"{device['host']}:{adb_port}"

    # First try a simple get-state.
    try:
        proc = subprocess.run(
            ["adb", "-s", target, "get-state"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        print(f"[{device['name']}] adb get-state timed out", file=sys.stderr)
        return False

    if proc.returncode == 0 and proc.stdout.strip() in ("device", "unknown", "offline"):
        # "unknown"/"offline" may still include unauthorized; that is handled later.
        return True

    # If we get here, try an explicit adb connect.
    print(f"[{device['name']}] Connecting to Firestick via adb connect...")
    try:
        proc_conn = subprocess.run(
            ["adb", "connect", target],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        print(f"[{device['name']}] adb connect timed out", file=sys.stderr)
        return False

    out = (proc_conn.stdout or "") + (proc_conn.stderr or "")
    out_lower = out.lower()
    if "connected" in out_lower or "already connected" in out_lower:
        print(f"[{device['name']}] adb connected.")
        return True

    print(f"[{device['name']}] Failed to connect via adb: {out.strip()}", file=sys.stderr)
    return False


def _check_unauthorized(proc: subprocess.CompletedProcess, device_name: str, context: str) -> bool:
    """
    Check adb output for "unauthorized" and log a hint if found.

    Returns True if unauthorized was detected.
    """
    combined = (proc.stdout or "") + (proc.stderr or "")
    if "unauthorized" in combined.lower():
        print(
            f"[{device_name}] ADB reported 'unauthorized' during {context}. "
            f"Check the Firestick for an 'Allow USB debugging' prompt and accept it "
            f"(preferably with 'Always allow from this computer' checked).",
            file=sys.stderr,
        )
        return True
    return False


def get_foreground_package(device: Dict[str, Any]) -> Optional[str]:
    """
    Try to determine which package currently has focus on the Firestick.

    Returns:
        package name (str) or None if it couldn't be determined.
    """
    proc = adb(device, "shell", "dumpsys", "window", "windows")
    if not proc:
        return None

    if _check_unauthorized(proc, device["name"], "window dump"):
        return None

    if proc.returncode != 0:
        return None

    out = proc.stdout

    # Typical pattern:
    #   mCurrentFocus=Window{... u0 com.package.name/com.ActivityName}
    m = re.search(r"mCurrentFocus=Window\{[^\s]+ [^\s]+ ([^/]+)/", out)
    if m:
        return m.group(1)

    # Fallback: activity dump
    proc2 = adb(device, "shell", "dumpsys", "activity", "activities")
    if proc2:
        if _check_unauthorized(proc2, device["name"], "activity dump"):
            return None
        if proc2.returncode == 0:
            m2 = re.search(r"mResumedActivity: .*? ([^/]+)/", proc2.stdout)
            if m2:
                return m2.group(1)

    return None


def is_media_playing(device: Dict[str, Any]) -> bool:
    """
    Check if any media session is currently in PLAYING state (state=3) on this device.

    This is generic: it doesn't try to differentiate between Alexa, Netflix,
    Prime Video, etc. It simply answers: "is something actively playing?"
    """
    proc = adb(device, "shell", "dumpsys", "media_session")
    if not proc:
        return False

    if _check_unauthorized(proc, device["name"], "media_session dump"):
        return False

    if proc.returncode != 0:
        return False

    out = proc.stdout

    # Crude but effective: state=3 usually indicates "PLAYING"
    return "state=3" in out


def launch_slideshow(device: Dict[str, Any]) -> None:
    """
    Launch the configured idle target app (slideshow/black-screen/etc.) on this device.
    """
    comp = device["slideshow_component"]
    print(f"[{device['name']}] Launching idle target app: {comp}")
    if "/" in comp:
        proc = adb(device, "shell", "am", "start", "-n", comp)
    else:
        proc = adb(
            device,
            "shell",
            "monkey",
            "-p",
            comp,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
    if not proc:
        print(f"[{device['name']}] Failed to launch target app (no adb result).", file=sys.stderr)
        return

    if _check_unauthorized(proc, device["name"], "target app launch"):
        return

    if proc.returncode == 0:
        print(f"[{device['name']}] Target app launch command sent.")
    else:
        print(
            f"[{device['name']}] Failed to launch target app: rc={proc.returncode}, "
            f"stdout={proc.stdout.strip()}, stderr={proc.stderr.strip()}",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# IDLE FSM
# ---------------------------------------------------------------------------


@dataclass
class IdleState:
    idle_seconds: float = 0.0


def update_idle_state(
    *,
    state: IdleState,
    home_screen: bool,
    in_target_app: bool,
    media_playing: bool,
    poll_interval: float,
    timeout: Optional[float],
) -> Tuple[IdleState, bool, bool]:
    """
    Advance the per-device idle FSM and decide whether to launch the idle app.

    Returns a tuple of (state, should_launch, idle_eligible).
    """

    idle_eligible = home_screen and not media_playing and not in_target_app

    if idle_eligible:
        state.idle_seconds += poll_interval
    else:
        state.idle_seconds = 0

    effective_timeout = 0 if timeout is None else timeout

    should_launch = idle_eligible and state.idle_seconds >= effective_timeout and not in_target_app

    if should_launch:
        state.idle_seconds = 0

    return state, should_launch, idle_eligible


# ---------------------------------------------------------------------------
# MQTT SUPPORT (OPTIONAL)
# ---------------------------------------------------------------------------

class MqttClientWrapper:
    """
    Thin wrapper around paho-mqtt so we can treat MQTT as optional.
    """

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.client = None

    def connect(self) -> None:
        if mqtt is None:
            print("[mqtt] paho-mqtt not installed; MQTT disabled.", file=sys.stderr)
            return

        self.client = mqtt.Client()

        username = self.cfg.get("username")
        password = self.cfg.get("password")
        if username:
            self.client.username_pw_set(username=username, password=password)

        host = self.cfg["host"]
        port = self.cfg["port"]

        try:
            self.client.connect(host, port, keepalive=60)
            # Use loop_start() to handle reconnects in the background.
            self.client.loop_start()
            print(f"[mqtt] Connected to {host}:{port}")
        except Exception as exc:  # noqa: BLE001
            print(f"[mqtt] Failed to connect to {host}:{port}: {exc}", file=sys.stderr)
            self.client = None

    def publish_state(self, topic_prefix: str, device_name: str, state: Dict[str, Any]) -> None:
        if self.client is None:
            return

        topic = f"{topic_prefix}/{device_name}/state"
        payload = json.dumps(state, separators=(",", ":"))
        try:
            self.client.publish(topic, payload=payload, qos=0, retain=False)
        except Exception as exc:  # noqa: BLE001
            print(f"[mqtt] Failed to publish to {topic}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------

def main_loop() -> None:
    """
    Main polling loop.

    For each device:
      - Ensure adb connection.
      - Check foreground package.
      - Check whether media is playing.
      - If on home screen, idle, and not already in target app → launch target app.
      - If idle_timer configured: if app+media state unchanged for >= timeout,
        and not playing + not in target app → launch target app.
      - Optionally publish state over MQTT.
    """
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"[startup] Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    poll_interval = config["poll_interval_seconds"]
    idle_timeout = config["idle_timeout_seconds"]
    devices = config["devices"]
    mqtt_cfg = config["mqtt"]
    config_path = config["config_path"]
    sources = config.get("sources", {})
    env_devices_count = config.get("env_devices_count", 0)
    env_present = config.get("env_present", False)
    idle_app = config.get("idle_app")
    idle_app_source = config.get("idle_app_source", "default")

    idle_enabled = idle_timeout is not None
    mqtt_enabled = mqtt_cfg is not None

    # Per-device runtime state for idle tracking.
    device_runtime: Dict[str, IdleState] = {}

    # MQTT setup
    mqtt_client_wrapper: Optional[MqttClientWrapper] = None
    topic_prefix: Optional[str] = None
    if mqtt_enabled:
        mqtt_client_wrapper = MqttClientWrapper(mqtt_cfg)
        mqtt_client_wrapper.connect()
        topic_prefix = mqtt_cfg["topic_prefix"]

    print("firestick-minder starting up...")
    if config_path:
        print(f"[startup] Config source: YAML file {config_path}")
    else:
        print("[startup] Config source: environment variables (env-only mode)")

    device_labels = [d["name"] for d in devices]
    print(
        f"[startup] Devices ({len(devices)}): {device_labels} "
        f"(source: {sources.get('devices', 'default')})"
    )
    print(
        f"[startup] Polling every {poll_interval} seconds "
        f"(source: {sources.get('poll_interval_seconds', 'default')})"
    )
    if idle_app:
        print(f"[startup] Idle app: {idle_app} (source: {idle_app_source})")
    else:
        print("[startup] Idle app: <none> (set MINDER_APP or per-device app if needed)")
    if idle_enabled:
        print(
            f"[startup] Idle timer enabled at {idle_timeout} seconds "
            f"(source: {sources.get('idle_timeout_seconds', 'default')})"
        )
    else:
        print(
            "[startup] Idle timer disabled (idle_timeout_seconds not configured). "
            f"(source: {sources.get('idle_timeout_seconds', 'default')})"
        )
    if mqtt_enabled:
        print(
            f"[startup] MQTT enabled with topic_prefix='{topic_prefix}' "
            f"(source: {sources.get('mqtt', 'default')})"
        )
    else:
        print(
            "[startup] MQTT disabled (no mqtt section configured). "
            f"(source: {sources.get('mqtt', 'default')})"
        )

    while True:
        loop_started = time.time()
        try:
            for device in devices:
                name = device.get("name", device.get("host", "unknown"))
                host = device.get("host")

                if not host:
                    print(f"[{name}] Device has no 'host' configured; skipping.", file=sys.stderr)
                    continue

                # Initialize per-device runtime state if needed.
                idle_state = device_runtime.setdefault(name, IdleState())

                # Make sure adb can talk to this device.
                if not ensure_connected(device):
                    # If we can't connect right now, skip this device for this tick.
                    print(f"[{name}] Not connected; will retry on next tick.")
                    continue

                foreground_pkg = get_foreground_package(device)
                media_playing = is_media_playing(device)

                slideshow_comp = device["slideshow_component"]
                slideshow_pkg = slideshow_comp.split("/")[0]
                home_packages = device.get("home_packages", set())

                home_screen = foreground_pkg in home_packages
                in_target_app = foreground_pkg == slideshow_pkg

                idle_state, should_launch, idle_eligible = update_idle_state(
                    state=idle_state,
                    home_screen=home_screen,
                    in_target_app=in_target_app,
                    media_playing=media_playing,
                    poll_interval=poll_interval,
                    timeout=idle_timeout if idle_enabled else None,
                )

                print(
                    f"[tick:{name}] foreground={foreground_pkg!r}, "
                    f"media_playing={media_playing}, "
                    f"home_screen={home_screen}, "
                    f"in_target_app={in_target_app}, "
                    f"idle_eligible={idle_eligible}, "
                    f"idle_seconds={idle_state.idle_seconds}, "
                    f"idle_timeout={idle_timeout}"
                )

                last_action = "none"

                if should_launch:
                    launch_slideshow(device)
                    last_action = "launched_target_from_idle"

                # MQTT telemetry: publish a per-device state snapshot.
                if mqtt_client_wrapper is not None and topic_prefix is not None:
                    state_payload = {
                        "name": name,
                        "host": host,
                        "foreground_package": foreground_pkg,
                        "media_playing": bool(media_playing),
                        "home_screen": bool(home_screen),
                        "in_target_app": bool(in_target_app),
                        "idle_eligible": bool(idle_eligible),
                        "idle_seconds": idle_state.idle_seconds,
                        "idle_timeout_seconds": idle_timeout,
                        "last_action": last_action,
                    }
                    mqtt_client_wrapper.publish_state(topic_prefix, name, state_payload)

            # Maintain approximate poll interval.
            elapsed = time.time() - loop_started
            sleep_for = max(0.0, poll_interval - elapsed)
            time.sleep(sleep_for)

        except KeyboardInterrupt:
            print("firestick-minder exiting on Ctrl+C")
            break
        except Exception as exc:  # noqa: BLE001
            # We don't want one unexpected exception to kill the whole daemon.
            print(f"[global] Error in main loop: {exc}", file=sys.stderr)
            time.sleep(poll_interval)


if __name__ == "__main__":
    ensure_adb_available()
    main_loop()
