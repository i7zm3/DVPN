Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

docker compose -f docker-compose.prod.yml build dvpn
docker compose -f docker-compose.prod.yml up -d --no-deps dvpn

for ($i = 0; $i -lt 40; $i++) {
  $health = docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' dvpn-prod 2>$null
  if ($health -eq "healthy") {
    Write-Host "[prod-update] Service healthy"
    exit 0
  }
  Start-Sleep -Seconds 3
}

throw "[prod-update] Timed out waiting for healthy container."
