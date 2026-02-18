# DVPN (Dockerized Crypto-Paid WireGuard Client)

This repository provides a containerized **distributed VPN client** with secure pool handshake and end-to-end encryption:

- Auto-discovery of provider pool
- Fastest-provider selection
- Randomized mesh endpoint cycling before selection
- Scheduled endpoint rotation every few minutes (with jitter)
- WireGuard end-to-end encryption
- Secure pool handshake before provider approval/connection
- Hard payment gate before any pool registration/discovery/approval calls
- SOCKS5 proxy for full-device/app routing
- Taskbar tray controls: **Start / Stop / Logs / Payments / Exit**
- Payment-gated access requiring **$9.99/month BTC** to wallet `1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn`

## Security Model

- TLS handshake enforced for pool/payment transport (`TLSv1.2+` minimum).
- Pool handshake sequence verifies payment token, marks provider approval, and only then activates tunnel routing.
- Pool approval requires a short-lived HMAC-signed lease (`client_ip`, nonce, expiry, signature) bound to token+provider.
- Fallback orchestration calls require HTTPS (`TLSv1.2+`) and can pin a custom CA cert.
- Local token storage uses PBKDF2 (salted key derivation) + integrity MAC.
- WireGuard private key remains environment-provided and is only written into runtime config in-container.
- Startup auto-configuration can detect local/public IPs and attempt UPnP UDP mapping for node publishing.
- Runtime defaults to non-persistent logs (`LOG_STDOUT=false`, `AUDIT_ENABLED=false`).
- Runtime metrics are exposed on control endpoint `/metrics` (Prometheus format).
- Runtime status exposes explicit phase transitions (`control_plane`, `control_plane_verified`, `tunnel_up`, `handshake_confirmed`, `traffic_verified`, `error`).

## Mesh Routing

- Each reconnect loop randomizes the provider list using a cryptographic RNG.
- The most recently used endpoint is deprioritized to improve anonymity and reduce sticky routing.
- `MESH_SAMPLE_SIZE` controls how many randomized endpoints are latency-tested each cycle.

## Bandwidth Policy

- Startup runs a throughput test (unless `BANDWIDTH_TOTAL_MBPS` is provided).
- On each new provider connection, allocator grants `50%` of measured total bandwidth.
- Grants are tracked per active connection and released on disconnect/reconnect.

## Tray Controls

Enable tray with `ENABLE_TRAY=true`.

Right-click menu actions:

- Start
- Stop
- Logs
- Payments
- Exit

The tray component uses `pystray` + `Pillow` when available; if missing, the VPN engine still runs normally.

## Payment + Approval Flow

1. User triggers **Payments** (tray)
2. Client requests checkout session from payment API (`checkout/start`)
3. After payment confirmation, payment API returns a valid token
4. Client stores token securely and authenticates against payment verify endpoint
5. On success, client calls pool approval endpoint (`/approve`) to mark access approved
6. Client connects WireGuard tunnel
7. If payment is inactive, pool access is blocked and tunnel is torn down

## Fallback Node Provisioning (Pool Failure Only)

If pool discovery or provider reachability fails, the client can provision a temporary remote node through a secure backend orchestrator.

- This fallback is disabled by default (`FALLBACK_ENABLED=false`).
- Fallback is only attempted after normal pool flow fails.
- Provisioning runs through `scripts/setup_fallback_node.sh` and requires an HTTPS orchestrator endpoint.
- The script posts user/payment/public-key metadata and expects provider JSON:
  - `id`
  - `endpoint`
  - `public_key`
  - optional `allowed_ips`

Fallback output is validated before use (endpoint shape, WireGuard public key format, CIDR parsing).

## Node Self-Registration

Each install can auto-register itself as a pool node at startup:

- derives WireGuard public key from local private key
- detects public endpoint (`NODE_PUBLIC_ENDPOINT` override supported)
- attempts UPnP port mapping (`UPNP_ENABLED=true`)
- posts registration to `POOL_URL/register`

Registration is best-effort and does not block normal client connectivity.

## Provider Internet Sharing (Secure Tunnel Egress)

To provide internet to another user securely through your tunnel:

1. Your node must be selected as a pool provider (public endpoint + valid WireGuard key).
2. Client connects to your node via WireGuard peer config (pool/worker controlled).
3. On the provider host, enable forwarding/NAT so peer traffic exits through WAN only.

Server-side commands (provider machine):

```bash
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -A POSTROUTING -o <wan_iface> -j MASQUERADE
iptables -A FORWARD -i wg0 -o <wan_iface> -j ACCEPT
iptables -A FORWARD -i <wan_iface> -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT
```

Replace `<wan_iface>` with your actual uplink interface (for example `wlp2s0` or `eth0`).

One-command helper:

```bash
sudo ./scripts/provider_enable_forwarding.sh <wan_iface>
```

Rollback helper (restores previous `ip_forward` and removes only rules added by DVPN):

```bash
sudo ./scripts/provider_disable_forwarding.sh
```

Native mode auto-restore:

- `scripts/native_run.sh` sets `PROVIDER_FORWARD_DISABLE_CMD` by default.
- On disconnect/stop/killswitch/payment-inactive teardown, runtime calls the restore script automatically.

Strict firewall mode (Linux):

- Blocks all inbound except WireGuard UDP port.
- Forces outbound through `wg0` only, with WireGuard/control-plane exceptions.
- Auto-enabled by default in `scripts/native_run.sh`, `one-click.sh`, and portable run scripts.

Manual commands:

```bash
sudo ./scripts/strict_firewall_enable.sh <wan_iface>
sudo ./scripts/strict_firewall_disable.sh
```

Security hardening for provider hosts:

- Keep WireGuard private keys secret.
- Only expose expected WireGuard UDP port(s).
- Restrict SSH/control/management ports by source IP allowlist.
- Rotate WireGuard keys and payment tokens periodically.
- Keep `PAID_TOKENS_SECRET` enforced in Worker so unpaid tokens cannot access pool.

## Payment Verification Rules

The client will only connect if verify response includes all:

- `active: true`
- `wallet: 1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn`
- `interval: monthly`
- `amount_usd >= 9.99`

## API Contracts

### Verify
`POST PAYMENT_API_URL`

```json
{
  "token": "<PAYMENT_TOKEN>",
  "provider_id": "provider-a",
  "required_wallet": "1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn",
  "required_price_usd": 9.99,
  "required_interval": "monthly"
}
```

### Checkout start
`POST PAYMENT_API_URL/checkout/start`

```json
{
  "user_id": "<USER_ID>",
  "required_wallet": "1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn",
  "required_price_usd": 9.99,
  "required_interval": "monthly"
}
```

### Pool approval
`POST POOL_URL/approve`

```json
{
  "provider_id": "provider-a",
  "token": "<PAYMENT_TOKEN>",
  "approved": true
}
```

## One-Click Install + Run

Linux/macOS:

```bash
./one-click.sh
```

Stop + rollback host forwarding changes:

```bash
./one-click-stop.sh
```

Windows (PowerShell):

```powershell
.\one-click.ps1
```

These scripts:

- install Docker if missing (best effort)
- create/update `.env` automatically with secure random values
- generate local TLS certs for dev orchestrator
- build and start the full stack in detached mode

## Internal Two-Node Handshake Test

Run a full local/private WireGuard handshake test with two nodes:

```bash
./scripts/local_handshake_test.sh
```

This script:

- builds the image
- starts a local pool service
- starts two nodes with private endpoints enabled
- verifies bidirectional WireGuard handshake

## Integration Matrix

Run an end-to-end matrix (unit tests + token gates + tunnel checks):

```bash
./scripts/integration_matrix.sh
```

## Portable Docker Bundle (Transfer To Others)

Build a portable image bundle:

```bash
./scripts/package_portable.sh
```

Bundle output is created in `dist/`:

- `dist/dvpn-node-image.tar.gz`
- `dist/one-click-run.sh`
- `dist/one-click-run.ps1`
- `dist/one-click-stop.sh`
- `dist/one-click-stop.ps1`
- `dist/README.md`
- `dist/INSTALL.md`
- `dist/docs/info.html`

On another device:

Linux/macOS:

```bash
./one-click-run.sh
```

Stop + rollback host forwarding changes:

```bash
./one-click-stop.sh
```

Windows PowerShell:

```powershell
.\one-click-run.ps1
```

These one-click scripts:

- load the image tar automatically
- generate runtime `.env` if missing
- run the node container with restart policy and persistent data
- attempt Docker install automatically (Linux/macOS/Windows with winget)

## Docs

- Architecture/security info page: `docs/info.html`
- Installation guide: `INSTALL.md`

## Native Host Run (Linux)

```bash
./scripts/native_setup_linux.sh
./scripts/native_run.sh
```

Notes:

- Tray icon requires a desktop session (X11/Wayland) and `ENABLE_TRAY=true`.
- If host privileges/tools are missing, WireGuard/SOCKS are auto-disabled instead of crashing.
- Tray menu includes: `Logs`, `Payments`, `Start On Boot`, `Killswitch`, `Restart`, `Exit`.
- Icon assets are generated in `assets/` (`dvpn-tray.png`, `dvpn-installer.png`, `dvpn-installer.ico`).
- Tray backend selection: `TRAY_BACKEND=qt` (recommended), `pystray`, or `auto`.

## Production Profile

Production stack files:

- `docker-compose.prod.yml`
- `.env.prod.example`
- `one-click-prod.sh`
- `one-click-prod.ps1`

Linux/macOS:

```bash
./one-click-prod.sh
```

Windows (PowerShell):

```powershell
.\one-click-prod.ps1
```

First run creates `.env.prod`; fill real production values and run again.

Production hardening included:

- `restart: always`
- healthcheck against control plane `/health`
- persistent volumes for token state and WireGuard config
- constrained resources (`mem_limit`, `cpus`, `pids_limit`)
- container runtime logs disabled (`logging.driver=none`)
- hardened container flags (`no-new-privileges`, `tmpfs` for `/tmp`)

### Production Ops

Rolling update (Linux/macOS):

```bash
./scripts/prod_update.sh
```

Rolling update (Windows PowerShell):

```powershell
.\scripts\prod_update.ps1
```

Backup persistent volumes (Linux/macOS):

```bash
./scripts/prod_backup.sh
```

Backup persistent volumes (Windows PowerShell):

```powershell
.\scripts\prod_backup.ps1
```

Restore from backup (Linux/macOS):

```bash
./scripts/prod_restore.sh backups/dvpn_data-YYYYMMDD-HHMMSS.tar.gz backups/dvpn_wg-YYYYMMDD-HHMMSS.tar.gz
```

Restore from backup (Windows PowerShell):

```powershell
.\scripts\prod_restore.ps1 .\backups\dvpn_data-YYYYMMDD-HHMMSS.tar.gz .\backups\dvpn_wg-YYYYMMDD-HHMMSS.tar.gz
```

Rotate production secrets:

```bash
./scripts/rotate_secrets.sh .env.prod
```

Create release artifacts + checksums:

```bash
./scripts/release_bundle.sh v1.0.0
```

Sign release artifacts (cosign or gpg):

```bash
./scripts/sign_release.sh v1.0.0
```

## Run (Dev, Auto Fallback)

```bash
cp .env.example .env
./scripts/gen_dev_certs.sh
docker compose up --build
```

The provided `docker-compose.yml` includes:

- `dvpn` client container
- `mock-orchestrator` HTTPS backend for payment + fallback provisioning
- TLS trust wiring via `certs/dev-ca.crt`
- forced pool failure (`POOL_URL=https://127.0.0.1:9/providers`) so fallback path is exercised

Quick check after startup:

```bash
./scripts/smoke_fallback.sh
```

## Fallback Environment

- `MESH_SAMPLE_SIZE`: randomized pool endpoints tested each reconnect (default `3`)
- `ENDPOINT_ROTATE_SECONDS`: rotate endpoint on a schedule (default `240`)
- `ENDPOINT_ROTATE_JITTER_SECONDS`: random rotation jitter (default `45`)
- `FALLBACK_ENABLED`: enable fallback remote node provisioning (`true/false`)
- `FALLBACK_SCRIPT_PATH`: setup script path (`scripts/setup_fallback_node.sh`)
- `FALLBACK_ORCHESTRATOR_URL`: secure backend provisioning API (`https://...`)
- `FALLBACK_TIMEOUT_SECONDS`: timeout for fallback setup
- `FALLBACK_CA_CERT`: optional CA certificate path for orchestrator TLS validation
- `SSL_CERT_FILE`: CA bundle path used by Python HTTPS clients (`ssl` default context)
- `AUTO_NETWORK_CONFIG`: enable auto local/public IP detection
- `UPNP_ENABLED`: enable UPnP port mapping attempts via `upnpc`
- `NODE_REGISTER_ENABLED`: register this install as a node (`POOL_URL/register`)
- `NODE_ID`: node identifier (auto-generated if empty)
- `NODE_PORT`: advertised UDP port for node endpoint
- `NODE_PUBLIC_ENDPOINT`: explicit `host:port` override if auto-detection is wrong
- `ALLOW_PRIVATE_ENDPOINTS`: allow local/private provider endpoints for dev only (`false` by default)
- `LOG_STDOUT`: keep runtime stdout logs (`false` by default)
- `AUDIT_ENABLED`: enable audit event output (`false` by default)
- `BANDWIDTH_TEST_URL`: HTTPS download endpoint used for throughput sampling
- `BANDWIDTH_SAMPLE_SECONDS`: sampling duration for throughput test
- `BANDWIDTH_TOTAL_MBPS`: override measured total bandwidth (set `0` to auto-test)

## Governance Files

- `SECURITY.md`
- `THREAT_MODEL.md`
- `PRODUCTION_CHECKLIST.md`

## Cloudflare Worker + Domain

Worker files:

- `wrangler.toml`
- `src/index.js`

Deploy:

```bash
npm i -g wrangler
wrangler login
wrangler deploy
```

Use worker endpoints in your app config:

- `POOL_URL=https://<worker-host>/providers`
- `PAYMENT_API_URL=https://<worker-host>/verify`
- `FALLBACK_ORCHESTRATOR_URL=https://<worker-host>`

For `dvpn.lol` with Spaceship nameservers (`launch1.spaceship.net`, `launch2.spaceship.net`):

1. Keep current nameservers and add DNS records in Spaceship:
   - `CNAME api` -> `<your-worker-subdomain>.workers.dev`
2. Point app settings to:
   - `https://api.dvpn.lol/providers`
   - `https://api.dvpn.lol/verify`
   - `https://api.dvpn.lol`

If you want Cloudflare-managed custom-domain routing features (zone routes), move domain nameservers to Cloudflare first.
