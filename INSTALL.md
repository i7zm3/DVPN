# DVPN Install & Run

## One-Click (Source Checkout)

Linux/macOS:

```bash
./one-click.sh
```

Windows (PowerShell):

```powershell
.\one-click.ps1
```

## Portable Distribution (For Sharing)

Build distributable bundle:

```bash
./scripts/package_portable.sh
```

This creates:

- `dist/dvpn-node-image.tar.gz`
- `dist/dvpn-node-image.tar.gz.sha256`
- `dist/one-click-run.sh`
- `dist/one-click-run.ps1`

## One-Click Run On Recipient Device

Linux/macOS:

```bash
./one-click-run.sh
```

Windows PowerShell:

```powershell
.\one-click-run.ps1
```

These scripts auto-load the image, auto-generate environment config, and start containerized DVPN.

## Health Check

```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/status
```

## Internal WireGuard Handshake Test

```bash
./scripts/local_handshake_test.sh
```

Expected: `PASS: bidirectional WireGuard handshake detected`
