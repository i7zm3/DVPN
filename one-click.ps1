Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Have-Cmd([string]$Name) {
  return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-DockerDesktop {
  if (Have-Cmd "docker") {
    return
  }
  if (Have-Cmd "winget") {
    winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
  }
  else {
    throw "Docker Desktop is required. Install from https://www.docker.com/products/docker-desktop/ then rerun."
  }
}

function Wait-Docker {
  for ($i = 0; $i -lt 90; $i++) {
    try {
      docker info | Out-Null
      return
    }
    catch {
      Start-Sleep -Seconds 2
    }
  }
  throw "Docker daemon did not become ready."
}

Ensure-DockerDesktop
Start-Process "Docker Desktop" -ErrorAction SilentlyContinue | Out-Null
Wait-Docker

python scripts/prepare_env.py

$CertDir = Join-Path $Root "certs"
New-Item -ItemType Directory -Force -Path $CertDir | Out-Null
$UnixRoot = "/w"

$CertScript = @'
set -e
cat > /tmp/dev-openssl.cnf <<EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
C = US
ST = Dev
L = Dev
O = DVPN Dev
OU = Dev
CN = mock-orchestrator

[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = mock-orchestrator
DNS.2 = localhost
IP.1 = 127.0.0.1
EOF
openssl genrsa -out /w/certs/dev-ca.key 2048
openssl req -x509 -new -nodes -key /w/certs/dev-ca.key -sha256 -days 3650 -out /w/certs/dev-ca.crt -subj "/CN=DVPN Dev CA"
openssl genrsa -out /w/certs/dev-server.key 2048
openssl req -new -key /w/certs/dev-server.key -out /tmp/dev-server.csr -config /tmp/dev-openssl.cnf
openssl x509 -req -in /tmp/dev-server.csr -CA /w/certs/dev-ca.crt -CAkey /w/certs/dev-ca.key -CAcreateserial -out /w/certs/dev-server.crt -days 825 -sha256 -extensions v3_req -extfile /tmp/dev-openssl.cnf
rm -f /tmp/dev-server.csr /tmp/dev-openssl.cnf /w/certs/dev-ca.srl
'@

docker run --rm -v "${Root}:${UnixRoot}" alpine:3.20 sh -lc "apk add --no-cache openssl >/dev/null && $CertScript"

docker compose up -d --build
Write-Host "Provider forwarding/NAT auto-setup is Linux-host only."
Write-Host "If running on Linux, use: sudo ./scripts/provider_enable_forwarding.sh <wan_iface>"
Write-Host "DVPN started. Check status: docker compose ps"
