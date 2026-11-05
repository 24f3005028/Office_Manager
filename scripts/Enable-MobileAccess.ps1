[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$tailscale = Join-Path $env:ProgramFiles 'Tailscale/tailscale.exe'
if (!(Test-Path -LiteralPath $tailscale)) { throw 'Install the official Tailscale client first.' }
$state = & $tailscale status --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $state.BackendState -ne 'Running') {
    throw 'Sign in to Tailscale on the office computer first. No service was exposed.'
}
$health = Invoke-RestMethod 'http://127.0.0.1:8002/health' -TimeoutSec 5
if ($health.service -ne 'office-mobile') { throw 'Start the Office desktop shortcut first.' }
# A private Serve endpoint only: never Funnel or the office dashboard/bridge ports.
& $tailscale serve --bg --https=443 http://127.0.0.1:8002
if ($LASTEXITCODE -ne 0) { throw 'Private HTTPS setup needs attention in Tailscale.' }
Write-Host 'Private mobile gateway configured. Only approved mobile app sessions can access data.'
& $tailscale serve status
