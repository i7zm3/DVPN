Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

docker compose down 2>$null | Out-Null
Write-Host "DVPN stopped."
Write-Host "If Linux host forwarding was enabled, run: sudo ./scripts/provider_disable_forwarding.sh"
