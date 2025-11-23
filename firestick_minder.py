#!/usr/bin/env python3
"""
firestick-minder

A tiny daemon that watches one or more Fire TV / Firestick devices over ADB.
If a device is on the Fire TV home screen and not currently playing media,
firestick-minder automatically launches a specified "slideshow" app
(e.g., a Plex photo/screensaver app).

Configuration is provided via a YAML file (default: ./config.yml) with:
- poll_interval_seconds
- devices: list of {name, host, home_packages, slideshow_component}

Non-destructive:
- No rooting, no custom ROM, no launcher patching.
- Stop the script/container and your Firesticks go back to normal behavior.
"""

import os
import subprocess
import time
import re
import sys
from typing import Dict, Any, List, Optional

import yaml

# ---------------------------------------------------------------------------
# CONFIG LOADING
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = "./config.yml"
ENV_CONFIG_VAR = "FIRESTICK_MINDER_CONFIG"


class ConfigError(Exception):
    """Raised for configuration-related issues."""


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load YAML configuration from the given path.

    Expected schema:
      poll_interval_seconds: int
      devices:
        - name: str
          host: str
          home_packages: [str, ...]
          slideshow_component: str  # "<package>/<Activity>"
    """
    config_path = path or os.environ.get(ENV_CONFIG_VAR, DEFAULT_CONFIG_PATH)

    if not os.path.exists(config_path):
        raise ConfigError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Failed to parse YAML config: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Top-level YAML config must be a mapping")

    poll_interval = data.get("poll_interval_seconds", 5)
    devices = data.get("devices", [])

    if not isinstance(poll_interval, int) or poll_interval <= 0:
        raise ConfigError("poll_interval_seconds must be a positive integer")

    if not isinstance(devices, list) or not devices:
        raise ConfigError("devices must be a non-empty list")

    # Normalize devices: ensure required keys exist and types are correct.
    norm_devices: List[Dict[str, Any]] = []
    for idx, dev in enumerate(devices):
        if not isinstance(dev, dict):
            raise ConfigError(f"Device entry at index {idx} must be a mapping")

        name = dev.get("name") or f"device_{idx}"
        host = dev.get("host")
        home_packages = dev.get("home_packages", [])
        slideshow_component = dev.get("slideshow_component")

        if not host or not isinstance(host, (str, int)):
            raise ConfigError(f"Device {name!r} is missing a valid 'host' field")

        if not slideshow_component or not isinstance(slideshow_component, str):
            raise ConfigError(f"Device {name!r} is missing 'slideshow_component'")

        if not isinstance(home_packages, list) or not home_packages:
            raise ConfigError(
                f"Device {name!r} must have a non-empty 'home_packages' list"
            )

        norm_devices.append(
            {
                "name": str(name),
                "host": str(host),
                "home_packages": set(map(str, home_packages)),
                "slideshow_component": slideshow_component,
            }
        )

    return {
        "poll_interval_seconds": poll_interval,
        "devices": norm_devices,
        "config_path": config_path,
    }


# ---------------------------------------------------------------------------
# ADB HELPERS
# ---------------------------------------------------------------------------

def adb(device: Dict[str, Any], *args: str, timeout: int = 5) -> Optional[subprocess.CompletedProcess]:
    """
    Run an adb command against a specific Firestick and return the CompletedProcess.
    """
    target = f"{device['host']}:5555"
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
    target = f"{device['host']}:5555"

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
    Launch the configured slideshow app on this device.
    """
    comp = device["slideshow_component"]
    print(f"[{device['name']}] Launching slideshow app: {comp}")
    proc = adb(device, "shell", "am", "start", "-n", comp)
    if not proc:
        print(f"[{device['name']}] Failed to launch slideshow (no adb result).", file=sys.stderr)
        return

    if _check_unauthorized(proc, device["name"], "slideshow launch"):
        return

    if proc.returncode == 0:
        print(f"[{device['name']}] Slideshow launch command sent.")
    else:
        print(
            f"[{device['name']}] Failed to launch slideshow: rc={proc.returncode}, "
            f"stdout={proc.stdout.strip()}, stderr={proc.stderr.strip()}",
            file=sys.stderr,
        )


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
      - If on home screen, idle, and not already in slideshow → launch slideshow.
    """
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"[startup] Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    poll_interval = config["poll_interval_seconds"]
    devices = config["devices"]
    config_path = config["config_path"]

    print("firestick-minder starting up...")
    print(f"Using config file: {config_path}")
    print(f"Configured devices: {[d['name'] for d in devices]}")
    print(f"Polling interval: {poll_interval} seconds")

    while True:
        try:
            for device in devices:
                name = device.get("name", device.get("host", "unknown"))
                host = device.get("host")

                if not host:
                    print(f"[{name}] Device has no 'host' configured; skipping.", file=sys.stderr)
                    continue

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

                print(
                    f"[tick:{name}] foreground={foreground_pkg!r}, "
                    f"media_playing={media_playing}, "
                    f"slideshow_pkg={slideshow_pkg!r}"
                )

                # Already in our slideshow app → do nothing.
                if foreground_pkg == slideshow_pkg:
                    continue

                # If any media is playing, assume user/Echo is doing something intentional.
                if media_playing:
                    continue

                # If we're on the Fire TV home/launcher, and idle, shove it into slideshow.
                if foreground_pkg in home_packages:
                    launch_slideshow(device)
                    continue

                # Otherwise: some other app is in foreground and not playing media.
                # For now, we leave it alone. (You could choose to force slideshow after
                # a timeout if you ever want more aggressive behavior.)
                continue

            time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("firestick-minder exiting on Ctrl+C")
            break
        except Exception as exc:
            # We don't want one unexpected exception to kill the whole daemon.
            print(f"[global] Error in main loop: {exc}", file=sys.stderr)
            time.sleep(poll_interval)


if __name__ == "__main__":
    main_loop()
