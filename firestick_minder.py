#!/usr/bin/env python3
"""
firestick-minder

A tiny daemon that watches one or more Fire TV / Firestick devices over ADB.
If a device is on the Fire TV home screen and not currently playing media,
firestick-minder automatically launches a specified "slideshow" app
(e.g., a Plex photo/screensaver app).

This script is designed to be edited in-place with your environment:

- Update the DEVICES list with your Firestick IPs and slideshow app components.
- Adjust POLL_INTERVAL_SECONDS if needed.
- Deploy as a systemd service on a small VM/LXC in your LAN.

Non-destructive:
- No rooting, no custom ROM, no launcher patching.
- Stop the script/service and your Firesticks go back to normal behavior.
"""

import subprocess
import time
import re
import sys
from typing import Dict, Any, List, Optional

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# How often to poll each Firestick for its current status.
# 5 seconds is a good default; you can lower this to 2–3 if you want faster reaction.
POLL_INTERVAL_SECONDS: int = 5

# Devices configuration.
# Replace the example entries below with your actual Firestick IPs and slideshow app info.
#
# Each entry should look like:
# {
#     "name": "livingroom",
#     "host": "192.168.10.101",  # <--- PUT YOUR FIRESTICK IP HERE
#
#     # Packages that represent the Fire TV "home" / launcher on this device.
#     # Usually one of:
#     #   - "com.amazon.tv.launcher"
#     #   - "com.amazon.firetv.launcher"
#     #   - Sometimes additional system UI packages, if needed.
#     "home_packages": {
#         "com.amazon.tv.launcher",
#         "com.amazon.firetv.launcher",
#     },
#
#     # The Activity we want to auto-launch when the device is idle on the home screen.
#     # Format: "<package.name>/<activity.class>"
#     # Example (FAKE): "com.example.slideshow/.MainActivity"
#     # To find this for your real app:
#     #   1) Install the app on the Firestick.
#     #   2) Run: adb shell pm list packages
#     #   3) Find the package, then:
#     #      adb shell dumpsys package com.example.slideshow | grep MAIN -A 1
#     "slideshow_component": "com.example.slideshow/.MainActivity",  # <--- PUT YOUR APP HERE
# }
#
# Add one entry per Firestick.

DEVICES: List[Dict[str, Any]] = [
    {
        "name": "livingroom",            # <--- FRIENDLY NAME (for logs only)
        "host": "192.168.10.101",        # <--- EXAMPLE IP - REPLACE WITH YOUR FIRESTICK IP
        "home_packages": {
            "com.amazon.tv.launcher",    # <--- REPLACE/CONFIRM BASED ON YOUR DEVICE
            "com.amazon.firetv.launcher"
        },
        "slideshow_component": "com.example.slideshow/.MainActivity",  # <--- REPLACE
    },
    {
        "name": "bedroom",
        "host": "192.168.10.102",        # <--- ANOTHER EXAMPLE IP
        "home_packages": {
            "com.amazon.tv.launcher",
            "com.amazon.firetv.launcher"
        },
        "slideshow_component": "com.example.slideshow/.MainActivity",
    },
    # Add more devices here as needed.
]

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
        # NOTE: "unknown"/"offline" can still include "unauthorized" cases.
        # We'll detect unauthorized in the individual adb() calls.
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


def get_foreground_package(device: Dict[str, Any]) -> Optional[str]:
    """
    Try to determine which package currently has focus on the Firestick.

    Returns:
        package name (str) or None if it couldn't be determined.
    """
    proc = adb(device, "shell", "dumpsys", "window", "windows")
    if not proc:
        return None

    # If the device is "unauthorized", adb will say so in stderr/stdout.
    if "unauthorized" in (proc.stdout + proc.stderr).lower():
        print(
            f"[{device['name']}] ADB reported 'unauthorized'. "
            f"Check the Firestick screen for a 'Allow USB debugging' prompt and accept it.",
            file=sys.stderr,
        )
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
    if proc2 and proc2.returncode == 0:
        if "unauthorized" in (proc2.stdout + proc2.stderr).lower():
            print(
                f"[{device['name']}] ADB reported 'unauthorized' in activity dump. "
                f"Approve debugging on the Firestick.",
                file=sys.stderr,
            )
            return None

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

    if "unauthorized" in (proc.stdout + proc.stderr).lower():
        print(
            f"[{device['name']}] ADB reported 'unauthorized' in media_session. "
            f"Approve debugging on the Firestick.",
            file=sys.stderr,
        )
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

    if "unauthorized" in (proc.stdout + proc.stderr).lower():
        print(
            f"[{device['name']}] ADB reported 'unauthorized' when launching slideshow. "
            f"Approve debugging on the Firestick.",
            file=sys.stderr,
        )
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
    print("firestick-minder starting up...")
    print(f"Configured devices: {[d['name'] for d in DEVICES]}")
    print(f"Polling interval: {POLL_INTERVAL_SECONDS} seconds")

    while True:
        try:
            for device in DEVICES:
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

            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("firestick-minder exiting on Ctrl+C")
            break
        except Exception as exc:
            # We don't want one unexpected exception to kill the whole daemon.
            print(f"[global] Error in main loop: {exc}", file=sys.stderr)
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main_loop()
