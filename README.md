# dvpn

dvpn is a prototype for a serverless peer-to-peer VPN controller on Linux and Android.
It takes a first step toward distributed WireGuard-style peer matching, local logs, and a local kill switch with IPv6 disabled.

## Features

- WireGuard-style key generation and configuration
- Local kill switch enforced on Linux with `iptables`
- IPv6 disabled system-wide for the VPN interface on Linux
- Local logs stored under `~/.dvpn/logs` on Linux and app storage on Android
- Simple single-click UI built with Tkinter on desktop and Jetpack Compose on Android
- Peer discovery via LAN UDP broadcast (proof of concept)
- Automatic peer rotation every 2 minutes when multiple peers are available

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Linux, you must also install WireGuard tools and run as root or with sufficient privileges:

```bash
sudo apt update
sudo apt install wireguard iptables python3-tk
```

## Run (Linux)

```bash
python -m dvpn
```

## Build (Android)

Open `android/` as an Android Studio project.

### Requirements

- Android Studio Flamingo or newer
- Android SDK 34
- Gradle 8.3+

### Run

Build and install the `app` module on a device or emulator.

## Notes

- This project is a prototype; Android uses `VpnService` and local peer discovery.
- The Android version captures IPv4 traffic through a VPN tunnel and avoids IPv6 routing.
- Logs remain local to the device.
