# firestick-minder

A tiny Python daemon that keeps your Firesticks on a quiet slideshow instead of the Fire TV home screen ads.

`firestick-minder` connects to one or more Fire TV / Firestick devices over ADB and checks their state every few seconds:

- If a device is on the **Fire TV home screen**,
- And **no media is currently playing**, 
- And it is **not already in your chosen slideshow app**, 

…then `firestick-minder` automatically launches the slideshow app.

Turn the daemon off, and your Firesticks go back to normal behavior.  
No rooting, no launcher replacement, no permanent changes.

---

## Features

- Supports multiple Firesticks from a single process.
- Non-destructive: no jailbreak, no system mods.
- Uses a simple YAML config file (`config.yml`).
- Can run:
  - directly on a Linux host (VM, LXC, etc.), or
  - in a Docker container (with optional `docker-compose`).

---

## Configuration (`config.yml`)

Configuration is provided via a YAML file. A template is included as `config.example.yml`.

Copy it to `config.yml` and edit:

```bash
cp config.example.yml config.yml

Example:

poll_interval_seconds: 5

devices:
  - name: livingroom
    host: 192.168.10.101
    home_packages:
      - com.amazon.tv.launcher
      - com.amazon.firetv.launcher
    slideshow_component: com.example.slideshow/.MainActivity

  - name: bedroom
    host: 192.168.10.102
    home_packages:
      - com.amazon.tv.launcher
      - com.amazon.firetv.launcher
    slideshow_component: com.example.slideshow/.MainActivity

Fields
•poll_interval_seconds
How often to poll each Firestick for its state.
5 seconds is a good default; you can lower this (e.g. 2–3) for faster reaction.
•devices (list)
Each entry defines one Firestick:
•name
Friendly name for logs ("livingroom", "bedroom", etc.).
•host
IP or hostname of the Firestick on your LAN.
firestick-minder connects to <host>:5555 via adb.
•home_packages
One or more package names that represent the Fire TV home / launcher on that device.
Common values:
•com.amazon.tv.launcher
•com.amazon.firetv.launcher
To discover the launcher package:

adb connect <FIRESTICK_IP>:5555
adb shell dumpsys window windows | grep mCurrentFocus

Look for a line containing something like:

mCurrentFocus=Window{... u0 com.amazon.tv.launcher/com.amazon.tv.launcher.ui.HomeActivity}

Use the package name (com.amazon.tv.launcher) in home_packages.

•slideshow_component
The Activity to launch for your slideshow/screensaver app.
Format: <package.name>/<ActivityClass>, e.g.:

slideshow_component: com.plexapp.android.screensaver/.MainActivity

To discover:

adb shell pm list packages
adb shell dumpsys package <your.package.name> | grep MAIN -A 1
```

---

Running without Docker (bare Linux / LXC)

Requirements
•Python 3.7+
•adb (Android platform-tools)
•PyYAML (pip install pyyaml)

Example on Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 android-sdk-platform-tools
pip install --user pyyaml
```

Clone or copy this repo:

```bash
mkdir -p /opt/firestick-minder
cd /opt/firestick-minder
# Place firestick_minder.py, config.example.yml, etc. here
cp config.example.yml config.yml
# edit config.yml as needed
```

Run:

```bash
python3 firestick_minder.py
```

To run as a systemd service, create a unit that calls:

```bash
ExecStart=/usr/bin/python3 /opt/firestick-minder/firestick_minder.py
WorkingDirectory=/opt/firestick-minder
Environment=FIRESTICK_MINDER_CONFIG=/opt/firestick-minder/config.yml
```

---

Running with Docker

### Build the image

From the repo root:

```bash
docker build -t firestick-minder:0.1.0 .
```

### Prepare config and ADB keys directory

```bash
cp config.example.yml config.yml
mkdir -p adb-keys
```

Edit config.yml with your real Firestick IPs and app details.

### docker run

Simple example:

```bash
docker run \
  --name firestick-minder \
  --restart=unless-stopped \
  -d \
  -v "$(pwd)/config.yml:/config/config.yml:ro" \
  -v "$(pwd)/adb-keys:/root/.android" \
  firestick-minder:0.1.0
```

### docker-compose

A docker-compose.yml is provided. From the repo root:

```bash
docker compose up -d
```

This will:
•Run the container as firestick-minder.
•Mount ./config.yml into /config/config.yml in the container.
•Persist ADB keys under ./adb-keys so you don’t get new debugging prompts after every container recreation.

If your networking setup requires, you can adjust docker-compose.yml to use:

```yaml
network_mode: "host"
```

(on Linux hosts) so the container shares the host’s IP.

---

ADB authorization notes

The first time firestick-minder connects from a given host/container, each Firestick will show an “Allow USB debugging?” prompt.

On each Firestick:
1.Make sure ADB debugging is enabled.
2.When prompted:
•Check “Always allow from this computer”
•Select OK

If firestick_minder.py logs messages about “unauthorized”, that usually means:
•The ADB trust was reset (system update, factory reset, etc.), or
•You rebuilt/moved the host and the ADB key changed (e.g., cleared ./adb-keys).

In that case, reconnect with:

```bash
adb connect <FIRESTICK_IP>:5555
```

and approve the prompt again on the Firestick.

---

Behavior details

On each poll:
•If the foreground package is the configured slideshow app → do nothing.
•If any media session is in state=3 (PLAYING) → do nothing (assume intentional playback).
•If the foreground package is one of the configured launcher home_packages and no media is playing → launch slideshow.

This gives you a soft “kiosk mode”:
•Use the Firestick normally for apps and playback.
•When it drifts back to the Fire TV home screen and idles, firestick-minder nudges it into your slideshow instead of leaving it on an ad-heavy home screen.

---

Environment variable
•FIRESTICK_MINDER_CONFIG
Override the default config path (defaults to ./config.yml on bare metal, and is set to /config/config.yml inside the Docker image).

Example:

```bash
FIRESTICK_MINDER_CONFIG=/opt/firestick-minder/my-config.yml python3 firestick_minder.py
```

---

Roadmap (future ideas)

Potential enhancements:
•Idle timeout logic from non-home apps (force slideshow after N minutes).
•Optional MQTT/HTTP status endpoint for integration with home automation.
•CLI flags for config path, log level, and one-shot diagnostics.
•Healthcheck endpoint for container orchestrators.

For now, firestick-minder focuses on being small, predictable, and easy to drop into a homelab.
Edit config.yml, give the container/host network access to your Firesticks, and let it quietly babysit them in the background.

---
