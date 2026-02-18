Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Container = "dvpn-node"

docker rm -f $Container 2>$null | Out-Null
Write-Host "Portable DVPN container stopped."
Write-Host "If you enabled Linux host forwarding, run: sudo ./provider_disable_forwarding.sh"
