Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if ($args.Count -lt 2) {
  throw "Usage: .\scripts\prod_restore.ps1 <dvpn_data tar.gz> <dvpn_wg tar.gz>"
}

$DataArchive = Resolve-Path $args[0]
$WgArchive = Resolve-Path $args[1]

docker compose -f docker-compose.prod.yml stop dvpn | Out-Null

$DataDir = Split-Path -Parent $DataArchive
$DataFile = Split-Path -Leaf $DataArchive
$WgDir = Split-Path -Parent $WgArchive
$WgFile = Split-Path -Leaf $WgArchive

docker run --rm `
  -v dvpn_dvpn_data:/dst `
  -v "${DataDir}:/backup:ro" `
  alpine:3.20 sh -lc "rm -rf /dst/* && tar -xzf /backup/$DataFile -C /dst"

docker run --rm `
  -v dvpn_dvpn_wg:/dst `
  -v "${WgDir}:/backup:ro" `
  alpine:3.20 sh -lc "rm -rf /dst/* && tar -xzf /backup/$WgFile -C /dst"

docker compose -f docker-compose.prod.yml up -d dvpn
Write-Host "[prod-restore] Completed"
