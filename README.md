# firestick-minder

> A tiny Python daemon that keeps your Firesticks on a quiet slideshow instead of the Fire TV home screen ads.

## What it does

`firestick-minder` connects to one or more Fire TV / Firestick devices over ADB and checks their state every few seconds:

- If a device is on the **Fire TV home screen**,
- And **no media is currently playing**,
- And it is **not already in your chosen slideshow app**,

…then `firestick-minder` automatically launches the slideshow app.

Turn the daemon off, and your Firesticks go back to normal behavior. No rooting, no launcher replacement, no permanent changes.

## Requirements

- A small Linux host (VM, LXC, etc.) on your LAN
- Python 3.7+
- `adb` (Android platform-tools)
- Fire TV / Firestick devices with:
  - Developer Options enabled
  - ADB Debugging enabled
  - ADB over network allowed
  - A stable IP address (DHCP reservation recommended)

## Install

Example install on Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip android-sdk-platform-tools

Clone this repo (or copy the files):

sudo mkdir -p /opt/firestick-minder
sudo chown "$(whoami)" /opt/firestick-minder
cd /opt/firestick-minder

# Copy firestick_minder.py into this directory

Make it executable:

chmod +x firestick_minder.py

Configure

Open firestick_minder.py and edit the DEVICES list:

DEVICES = [
    {
        "name": "livingroom",
        "host": "192.168.10.101",  # <--- REPLACE with your Firestick IP
        "home_packages": {
            "com.amazon.tv.launcher",
            "com.amazon.firetv.launcher",
        },
        "slideshow_component": "com.example.slideshow/.MainActivity",  # <--- REPLACE
    },
    # Add more devices as needed...
]

1. Find your Firestick IP

From your router/OPNsense, or directly on the Fire TV network settings.

2. Confirm the launcher package

On the Firestick home screen, run from your host:

adb connect <FIRESTICK_IP>:5555
adb shell dumpsys window windows | grep mCurrentFocus

Look for something like:

mCurrentFocus=Window{... u0 com.amazon.tv.launcher/com.amazon.tv.launcher.ui.HomeActivity}

Use that package name (com.amazon.tv.launcher) in home_packages.

3. Find your slideshow app component

Install your slideshow/screensaver app on the Firestick, then:

adb shell pm list packages
adb shell dumpsys package <your.package.name> | grep MAIN -A 1

Use the package/.ActivityName line as your slideshow_component, e.g.:

"slideshow_component": "com.plexapp.android.screensaver/.MainActivity",

4. Poll interval

By default, firestick-minder polls every 5 seconds:

POLL_INTERVAL_SECONDS: int = 5

You can reduce this (e.g. to 3) for faster reaction at the cost of slightly more ADB chatter.

Run as a service (systemd)

Copy the example service file:

sudo mkdir -p /etc/systemd/system
sudo cp systemd/firestick-minder.service /etc/systemd/system/firestick-minder.service

Edit the ExecStart line in the service file to match the actual path to firestick_minder.py.

Then:

sudo systemctl daemon-reload
sudo systemctl enable firestick-minder.service
sudo systemctl start firestick-minder.service

Check status:

systemctl status firestick-minder.service
journalctl -u firestick-minder.service -f

Behavior
	•	If any media is playing (state=3 from dumpsys media_session), firestick-minder does not interfere.
	•	If the foreground app is the slideshow app, it does nothing.
	•	If the foreground app is one of the configured Fire TV launcher packages and no media is playing, it launches the slideshow.

This gives you a soft “kiosk mode”:
	•	Use the Firestick normally.
	•	When it falls back to the home screen and idles, firestick-minder moves it into a photo slideshow instead of leaving it as an ad billboard.

ADB authorization notes

The first time you connect from the host running firestick-minder, the Firestick will show an “Allow USB debugging?” prompt.

Make sure to:
	•	Check “Always allow from this computer”
	•	Select OK

If firestick_minder.py logs messages about “unauthorized”, that usually means:
	•	The ADB trust was reset (system update, factory reset, etc.), or
	•	You rebuilt/moved the host and the ADB key changed.

In that case, reconnect with adb connect and approve the prompt again on the Firestick.

Roadmap (future ideas)
	•	Optional external config file (YAML/JSON).
	•	Idle timeout logic (force slideshow even from other apps after N minutes).
	•	MQTT/HTTP status endpoint for integration with home automation.
	•	Per-app rules (e.g., ignore certain apps, treat others as “idle”).

For now, firestick-minder is intentionally tiny and simple: a single Python file, a small config block, and a systemd service.

---
