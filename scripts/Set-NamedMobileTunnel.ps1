[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$directory = Join-Path $repo 'data/cloudflare'
$cloudflared = Join-Path $directory 'cloudflared.exe'
if (!(Test-Path -LiteralPath $cloudflared)) {
    throw 'Place the official Windows cloudflared.exe in data/cloudflare first.'
}

$name = 'hst-tunnel'
$hostname = 'hst-tunnel.brewwithcrew.com'
$profileDirectory = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.cloudflared'
$cert = Join-Path $profileDirectory 'cert.pem'
if (!(Test-Path -LiteralPath $cert)) {
    throw 'Run .\data\cloudflare\cloudflared.exe tunnel login and authorize brewwithcrew.com first.'
}

$listing = & $cloudflared tunnel --origincert $cert list --name $name --output json
if ($LASTEXITCODE -ne 0) { throw 'Could not list tunnels in the authorized Cloudflare account.' }
$tunnel = ($listing -join "`n" | ConvertFrom-Json) | Where-Object { $_.name -ceq $name }
if (!$tunnel) {
    & $cloudflared tunnel --origincert $cert create $name
    if ($LASTEXITCODE -ne 0) { throw "Could not create Cloudflare tunnel '$name'." }
    $listing = & $cloudflared tunnel --origincert $cert list --name $name --output json
    if ($LASTEXITCODE -ne 0) { throw 'Could not retrieve the new Cloudflare tunnel.' }
    $tunnel = ($listing -join "`n" | ConvertFrom-Json) | Where-Object { $_.name -ceq $name }
}

$id = [Guid]::Empty
if (![Guid]::TryParse([string]$tunnel.id, [ref]$id)) { throw 'Cloudflare did not return a tunnel UUID.' }
$credentials = Join-Path $profileDirectory "$id.json"
if (!(Test-Path -LiteralPath $credentials)) {
    throw "Tunnel $id exists, but its locally managed credentials file is missing: $credentials"
}

$configPath = Join-Path $directory 'named-tunnel.yml'
$config = @"
tunnel: $id
credentials-file: '$($credentials.Replace("'", "''"))'
ingress:
  - hostname: $hostname
    path: ^/mobile/v1/
    service: http://127.0.0.1:8002
    originRequest:
      httpHostHeader: office-mobile-tunnel
  - service: http_status:404
"@
[IO.File]::WriteAllText($configPath, $config, (New-Object Text.UTF8Encoding($false)))
& $cloudflared tunnel --config $configPath ingress validate
if ($LASTEXITCODE -ne 0) { throw 'Named tunnel configuration failed validation.' }

Write-Host "Tunnel UUID: $id"
Write-Host "DNS: Proxied CNAME $hostname -> $id.cfargotunnel.com"
Write-Host 'Start the connector using the Office WhatsApp Sender shortcut.'
