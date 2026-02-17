Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Image = if ($env:DVPN_IMAGE) { $env:DVPN_IMAGE } else { "dvpn-node:portable" }
$Tar = Join-Path $Root "dvpn-node-image.tar.gz"
$DataDir = Join-Path $HOME ".dvpn-node"
$EnvFile = Join-Path $DataDir ".env"
$Container = "dvpn-node"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
  } else {
    throw "Docker Desktop is required. Install it and rerun."
  }
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

for ($i = 0; $i -lt 90; $i++) {
  try {
    docker info | Out-Null
    break
  } catch {
    Start-Sleep -Seconds 2
  }
  if ($i -eq 89) { throw "Docker daemon did not become ready." }
}

$loaded = $true
try { docker image inspect $Image | Out-Null } catch { $loaded = $false }
if (-not $loaded) {
  if (-not (Test-Path $Tar)) { throw "Missing image archive: $Tar" }
  Get-Content -Encoding Byte $Tar | docker load | Out-Null
}

if (-not (Test-Path $EnvFile)) {
  function Rand([int]$n=32) {
    $chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    -join ((1..$n) | ForEach-Object { $chars[(Get-Random -Minimum 0 -Maximum $chars.Length)] })
  }
  $WGKey = docker run --rm --entrypoint sh $Image -lc "wg genkey"
  @"
POOL_URL=https://dvpn-worker.i7zm1n3.workers.dev/providers
PAYMENT_API_URL=https://dvpn-worker.i7zm1n3.workers.dev/verify
PAYMENT_PORTAL_URL=https://dvpn-worker.i7zm1n3.workers.dev/portal
PAYMENT_TOKEN=$(Rand 32)
USER_ID=user-$(Rand 12)
WG_PRIVATE_KEY=$WGKey
WG_ADDRESS=10.66.0.2/32
WG_DNS=
WG_PERSISTENT_KEEPALIVE=25
SOCKS_PORT=1080
CONNECT_TIMEOUT_SECONDS=5
RETRY_SECONDS=15
ENDPOINT_ROTATE_SECONDS=240
ENDPOINT_ROTATE_JITTER_SECONDS=45
ENABLE_TRAY=false
CONTROL_HOST=127.0.0.1
CONTROL_PORT=8765
TOKEN_STORE_PATH=/var/lib/dvpn/token.store
TOKEN_STORE_PASSPHRASE=$(Rand 32)
MESH_SAMPLE_SIZE=3
LOG_STDOUT=false
AUDIT_ENABLED=false
FALLBACK_ENABLED=true
FALLBACK_SCRIPT_PATH=/app/scripts/setup_fallback_node.sh
FALLBACK_ORCHESTRATOR_URL=https://dvpn-worker.i7zm1n3.workers.dev
FALLBACK_TIMEOUT_SECONDS=30
AUTO_NETWORK_CONFIG=true
UPNP_ENABLED=true
NODE_REGISTER_ENABLED=true
NODE_ID=node-$(Rand 12)
NODE_PORT=51820
NODE_PUBLIC_ENDPOINT=
ALLOW_PRIVATE_ENDPOINTS=false
BANDWIDTH_TEST_URL=https://speed.cloudflare.com/__down?bytes=25000000
BANDWIDTH_SAMPLE_SECONDS=4
BANDWIDTH_TOTAL_MBPS=0
ENABLE_WIREGUARD=true
WG_QUICK_CMD=wg-quick
WG_CONFIG_PATH=/tmp/dvpn/wg0.conf
ENABLE_SOCKS=false
DANTED_CMD=danted
DANTED_TEMPLATE_PATH=/app/scripts/danted.conf.template
DANTED_CONFIG_PATH=/tmp/dvpn/danted.conf
"@ | Set-Content -Path $EnvFile -NoNewline
}

docker rm -f $Container 2>$null | Out-Null
docker run -d --name $Container --restart unless-stopped --privileged --log-driver none --device /dev/net/tun:/dev/net/tun --env-file $EnvFile -p 8765:8765 -p 51820:51820/udp -v "${DataDir}:/var/lib/dvpn" $Image | Out-Null

Write-Host "DVPN started in container '$Container'."
Write-Host "Logs: docker logs --tail 60 $Container"
Write-Host "Health: curl http://127.0.0.1:8765/health"
