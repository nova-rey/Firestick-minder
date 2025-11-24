# firestick-minder

A tiny Python daemon that keeps your Firesticks in an "idle target" app instead of the Fire TV home screen ads.

`firestick-minder` connects to one or more Fire TV / Firestick devices over ADB and checks their state every few seconds:

- If a device is on the **Fire TV home screen**, and
- **No media is currently playing**, and
- It is **not already in your chosen idle target app**, 

…then `firestick-minder` automatically launches that idle target app.

Optionally, you can enable:

- An **idle timer** that also treats "sitting in any app doing nothing" as a trigger.
- **MQTT telemetry**, so your smart home can see and react to Firestick state.

Turn the daemon off, and your Firesticks go back to normal behavior.  
No rooting, no launcher replacement, no permanent changes.

---

## Features

- Supports multiple Firesticks from a single process.
- Non-destructive: no jailbreak, no system mods.
- Uses a simple YAML config file (`config.yml`).
- Optional idle timer:
  - After N seconds of inactivity in any non-target app (no media playing), launch the target app.
- Optional MQTT telemetry:
  - Publishes per-device JSON state to an MQTT broker for smart home integration.
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

# Optional: enable idle timer beyond the home screen.
# If omitted, only the home-screen path will auto-launch the target app.
# idle_timeout_seconds: 300  # 5 minutes

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

# Optional MQTT integration
# mqtt:
#   host: "192.168.10.50"
#   port: 1883
#   topic_prefix: "home/firestick"
#   # username: "myuser"
#   # password: "mypassword"
```

Fields
•poll_interval_seconds
How often to poll each Firestick for its state.
5 seconds is a good default; you can lower this (e.g. 2–3) for faster reaction.
•idle_timeout_seconds (optional)
If set to a positive integer, firestick-minder will also treat idle time inside any non-target, non-home app (with no media playing) as a trigger:
•If a device sits in the same app with no media playing for at least idle_timeout_seconds,
•And it is not already in the configured idle target app,
•firestick-minder will launch the idle target app.
If this field is omitted, the idle timer is disabled; only the home-screen behavior applies.
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
The Activity to launch for your idle target app. This does not need to be a slideshow; it can be:
•A photo slideshow app,
•A black-screen app,
•A minimalist clock,
•Any other screensaver-style/ambient app you prefer.
Format: <package.name>/<ActivityClass>, e.g.:

slideshow_component: com.plexapp.android.screensaver/.MainActivity

To discover:

adb shell pm list packages
adb shell dumpsys package <your.package.name> | grep MAIN -A 1


•mqtt (optional)
If present, firestick-minder will publish per-device state over MQTT.
Fields:
•host – MQTT broker hostname or IP.
•port – Broker port (default 1883).
•topic_prefix – Base topic under which device state will be published.
Example: home/firestick → device state published to home/firestick/<name>/state.
•username / password (optional) – Credentials for authenticated brokers.

The published payload is JSON, e.g.:

{
  "name": "livingroom",
  "host": "192.168.10.101",
  "foreground_package": "com.amazon.tv.launcher",
  "media_playing": false,
  "home_screen": true,
  "in_target_app": false,
  "idle_seconds": 12,
  "idle_timeout_seconds": 300,
  "last_action": "launched_target_from_home"
}


## Configuration via Environment Variables

firestick-minder now supports configuration using environment variables.
Environment variables override values in `config.yml`. If an env var is not
provided, the value falls back to YAML. Env-only setups are fully supported.

### Global Variables

| Variable               | Description                      |
|------------------------|----------------------------------|
| FSM_POLL_INTERVAL      | Poll interval (seconds)          |
| FSM_IDLE_TIMEOUT       | Idle timeout (seconds)           |
| FSM_MQTT_ENABLED       | true/false                       |
| FSM_MQTT_HOST          | MQTT broker host                 |
| FSM_MQTT_PORT          | MQTT port                        |
| FSM_MQTT_TOPIC_PREFIX  | Base MQTT topic                  |
| FSM_LOG_LEVEL          | info/debug                       |

### Device Variables

Devices are indexed:

```
FSM_DEVICE_1_HOST=192.168.3.50
FSM_DEVICE_1_NAME=livingroom
FSM_DEVICE_1_IDLE_APP=com.example.slideshow
```

To add more devices, increment:

```
FSM_DEVICE_2_HOST=192.168.3.51
FSM_DEVICE_2_NAME=bedroom
FSM_DEVICE_2_IDLE_APP=com.example.black
```

### Example Portainer Environment Block

```
FSM_POLL_INTERVAL=5
FSM_IDLE_TIMEOUT=300
FSM_MQTT_ENABLED=false
FSM_DEVICE_1_HOST=192.168.3.50
FSM_DEVICE_1_NAME=livingroom
FSM_DEVICE_1_IDLE_APP=com.example.slideshow
```

Environment variables take precedence over YAML.


⸻

Running without Docker (bare Linux / LXC)

Requirements
•Python 3.7+
•adb (Android platform-tools)
•PyYAML
•paho-mqtt (only used if mqtt is configured, but installed by default in this setup)

Example on Debian/Ubuntu:

sudo apt update
sudo apt install -y python3 android-sdk-platform-tools
pip install --user pyyaml paho-mqtt

Clone or copy this repo:

mkdir -p /opt/firestick-minder
cd /opt/firestick-minder
# Place firestick_minder.py, config.example.yml, etc. here
cp config.example.yml config.yml
# edit config.yml as needed

Run:

python3 firestick_minder.py

To run as a systemd service, create a unit that calls:

ExecStart=/usr/bin/python3 /opt/firestick-minder/firestick_minder.py
WorkingDirectory=/opt/firestick-minder
Environment=FIRESTICK_MINDER_CONFIG=/opt/firestick-minder/config.yml


⸻

Running with Docker

Build the image

From the repo root:

docker build -t firestick-minder:0.2.0 .

Prepare config and ADB keys directory

cp config.example.yml config.yml
mkdir -p adb-keys

Edit config.yml with your real Firestick IPs, idle target app, and (optionally) MQTT settings.

docker run

Example:

docker run \
  --name firestick-minder \
  --restart=unless-stopped \
  -d \
  -v "$(pwd)/config.yml:/config/config.yml:ro" \
  -v "$(pwd)/adb-keys:/root/.android" \
  firestick-minder:0.2.0

docker-compose

A docker-compose.yml is provided. From the repo root:

docker compose up -d

This will:
•Run the container as firestick-minder.
•Mount ./config.yml into /config/config.yml in the container.
•Persist ADB keys under ./adb-keys so you don’t get new debugging prompts after every container recreation.

If your networking setup requires, you can adjust docker-compose.yml to use:

network_mode: "host"

(on Linux hosts) so the container shares the host’s IP.

⸻

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

adb connect <FIRESTICK_IP>:5555

and approve the prompt again on the Firestick.

⸻

Behavior details

On each poll, for each device:
•foreground_package is read from the Firestick.
•media_playing is inferred from dumpsys media_session (state=3 = playing).
•home_screen is true if the foreground package is in home_packages.
•in_target_app is true if the foreground package matches the target app package.

Actions:
•If home_screen == true, media_playing == false, and in_target_app == false:
•→ Launch the idle target app (slideshow_component).
•If idle_timeout_seconds is configured and:
•Not in the target app, and
•Not on the home screen, and
•Not playing media, and
•The combination of foreground app + media state has been unchanged for at least idle_timeout_seconds:
•→ Launch the idle target app.

After launching the target app, idle tracking is reset for that device.

If MQTT is configured, a JSON state snapshot is published on each poll to:

<mqtt.topic_prefix>/<device.name>/state


⸻

Environment variable
•FIRESTICK_MINDER_CONFIG
Override the default config path (defaults to ./config.yml on bare metal, and is set to /config/config.yml inside the Docker image).

Example:

FIRESTICK_MINDER_CONFIG=/opt/firestick-minder/my-config.yml python3 firestick_minder.py


⸻

Roadmap (future ideas)

Potential enhancements:
•Command topics over MQTT (e.g., request specific apps to launch).
•Idle behavior exceptions (apps that should never be auto-replaced).
•Home Assistant auto-discovery.
•Simple HTTP status/health endpoint.

For now, the focus of v0.2 is optional idle behavior and MQTT telemetry, while keeping the base configuration and behavior simple.

---

No tests are required for this update. Ensure all four files:

- `firestick_minder.py`
- `config.example.yml`
- `Dockerfile`
- `README.md`

are fully replaced with the provided contents.

## Releases & Docker Images

This project publishes Docker images to Docker Hub from GitHub Actions.

When a tag matching `v*.*.*` is pushed (for example `v0.3.0`), GitHub Actions
builds the image and publishes it to:

- `novarey4200/firestick-minder:0.3.0`
- `novarey4200/firestick-minder:latest`

To cut a new release locally:

1. Update the version in the project as needed.
2. Commit your changes.
3. Create and push a tag:

   ```bash
   git tag v0.3.0
   git push origin v0.3.0
   ```

Within a few minutes, the new image will be available on Docker Hub.
