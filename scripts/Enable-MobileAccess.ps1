[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$cloudflared = Join-Path $repo 'data/cloudflare/cloudflared.exe'
if (!(Test-Path -LiteralPath $cloudflared)) {
    $command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if (!$command) { throw 'Install cloudflared or place it at data/cloudflare/cloudflared.exe. See mobile/README.md.' }
    $cloudflared = $command.Source
}

$gateway = 'http://127.0.0.1:8002'
try { $health = Invoke-RestMethod "$gateway/health" -TimeoutSec 5 }
catch { throw 'Start Office Dashboard on this PC before starting the tunnel.' }
if ($health.service -ne 'office-mobile' -or !$health.cloudflare_ready) {
    throw 'Restart the mobile gateway with the current Start-Office.cmd before starting the tunnel.'
}

# Use a separate, empty config so a machine-wide tunnel configuration cannot be loaded.
$config = Join-Path $repo 'data/cloudflare/quick-tunnel.yml'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $config) | Out-Null
Set-Content -LiteralPath $config -Encoding ASCII -Value '{}'
Write-Host 'Starting a free Cloudflare Quick Tunnel. Copy the printed HTTPS address into the app.'
Write-Host 'Keep this terminal running. Restarting the tunnel gives it a new address.'
& $cloudflared tunnel --config $config --no-autoupdate --url $gateway --http-host-header office-mobile-tunnel
if ($LASTEXITCODE -ne 0) { throw "Cloudflare Quick Tunnel exited with code $LASTEXITCODE." }
