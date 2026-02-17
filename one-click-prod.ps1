Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".env.prod")) {
  Copy-Item ".env.prod.example" ".env.prod"
  Write-Host "Created .env.prod from template. Fill production endpoints/tokens before rerunning."
  exit 0
}

docker compose -f docker-compose.prod.yml up -d --build
Write-Host "Production stack started. Check: docker compose -f docker-compose.prod.yml ps"
