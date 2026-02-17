Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$BackupDir = if ($args.Count -ge 1) { $args[0] } else { Join-Path $Root "backups" }
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$DataName = "dvpn_data-$Stamp.tar.gz"
$WgName = "dvpn_wg-$Stamp.tar.gz"

docker run --rm `
  -v dvpn_dvpn_data:/src:ro `
  -v "${BackupDir}:/backup" `
  alpine:3.20 sh -lc "tar -czf /backup/$DataName -C /src ."

docker run --rm `
  -v dvpn_dvpn_wg:/src:ro `
  -v "${BackupDir}:/backup" `
  alpine:3.20 sh -lc "tar -czf /backup/$WgName -C /src ."

Write-Host "[prod-backup] Completed: $DataName, $WgName"
