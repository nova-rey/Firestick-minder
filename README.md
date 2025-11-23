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
