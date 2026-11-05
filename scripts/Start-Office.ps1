[CmdletBinding()]
param([switch]$CheckOnly, [switch]$NoBrowser, [switch]$Rebuild)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo 'backend'
$frontend = Join-Path $repo 'frontend'
$bridge = Join-Path $repo 'whatsapp-bridge'
$logs = Join-Path $repo 'data\launcher'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$mutex = New-Object System.Threading.Mutex($false, 'Local\OfficeDocumentDashboardLauncher')
$ownsMutex = $false

function Invoke-Checked([string]$Executable, [string[]]$Arguments, [string]$Directory) {
    Push-Location -LiteralPath $Directory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Command failed in $Directory (exit $LASTEXITCODE)." }
    } finally { Pop-Location }
}

function Test-BuildNeeded([string]$Marker, [string[]]$Inputs) {
    if ($Rebuild -or !(Test-Path -LiteralPath $Marker)) { return $true }
    $built = (Get-Item -LiteralPath $Marker).LastWriteTimeUtc
    foreach ($inputPath in $Inputs) {
        if (!(Test-Path -LiteralPath $inputPath)) { continue }
        $item = Get-Item -LiteralPath $inputPath
        if ($item.PSIsContainer) {
            if (Get-ChildItem -LiteralPath $inputPath -Recurse -File |
                Where-Object { $_.LastWriteTimeUtc -gt $built } | Select-Object -First 1) { return $true }
        } elseif ($item.LastWriteTimeUtc -gt $built) { return $true }
    }
    return $false
}

function Get-Listener([int]$Port) {
    return Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Get-ServiceResponse([string]$Url, [hashtable]$Headers = @{}) {
    if ($Url.EndsWith('/whatsapp-bill-sender')) {
        return (Invoke-WebRequest -UseBasicParsing -Uri $Url -Headers $Headers -TimeoutSec 3).Content
    }
    return Invoke-RestMethod -Uri $Url -Headers $Headers -TimeoutSec 3
}

function Start-LocalService {
    param([string]$Name, [int]$Port, [string]$Executable, [string[]]$Arguments,
        [string]$Directory, [string]$Url, [scriptblock]$Validate,
        [hashtable]$Headers = @{})
    $listener = Get-Listener $Port
    if ($null -ne $listener) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if (!$owner.CommandLine -or $owner.CommandLine.IndexOf($Directory, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw "Port $Port belongs to a process outside this workspace. Close the conflicting service and retry."
        }
        try {
            $response = Get-ServiceResponse $Url $Headers
            if (!(& $Validate $response)) { throw 'Unexpected service response' }
        } catch { throw "Port $Port is occupied but $Name is not healthy. Close the conflicting service and retry." }
        Write-Host "$Name is already running."
        return
    }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdout = Join-Path $logs "$Name-$stamp.out.log"
    $stderr = Join-Path $logs "$Name-$stamp.err.log"
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $Directory `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Write-Host "Starting $Name..."
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) { throw "$Name exited. See $stderr" }
        try {
            $response = Get-ServiceResponse $Url $Headers
            if (& $Validate $response) {
                Write-Host "$Name is listening on port $Port."
                return
            }
        } catch { }
        Start-Sleep -Milliseconds 600
    }
    throw "$Name did not become healthy within 90 seconds. See $stderr. Started services remain available; retry after resolving the error."
}

try {
    try { $ownsMutex = $mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (!$ownsMutex) { Write-Host 'Office Dashboard is already starting.'; exit 0 }
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    if (!(Test-Path -LiteralPath $python)) { throw 'Create backend\.venv and install backend\requirements.txt first. See README.md.' }
    Invoke-Checked $python @('-c', 'import fastapi, uvicorn, httpx, pymupdf, openpyxl, xlrd, multipart, google.auth, requests, pywinauto; from app.config import Settings; Settings()') $backend
    foreach ($file in @('frontend\node_modules\next\dist\bin\next',
        'whatsapp-bridge\node_modules\typescript\bin\tsc', 'whatsapp-bridge\node_modules\whatsapp-web.js\package.json')) {
        if (!(Test-Path -LiteralPath (Join-Path $repo $file))) { throw "Missing $file. Run bun install in frontend and whatsapp-bridge first." }
    }
    Push-Location -LiteralPath $backend
    try {
        $backendJson = & $python -c 'import json; from app.config import Settings; s=Settings(); print(json.dumps(dict(url=s.whatsapp_bridge_url, key=s.whatsapp_bridge_api_key, origins=s.cors_origin_list)))'
        if ($LASTEXITCODE -ne 0) { throw 'Backend configuration could not be read.' }
        $backendConfig = $backendJson | ConvertFrom-Json
    } finally { Pop-Location }
    $bridgeJson = & $node (Join-Path $PSScriptRoot 'bridge-config.cjs')
    if ($LASTEXITCODE -ne 0) { throw 'Bridge configuration could not be read.' }
    $bridgeConfig = $bridgeJson | ConvertFrom-Json
    $frontendJson = & $node (Join-Path $PSScriptRoot 'frontend-config.cjs')
    if ($LASTEXITCODE -ne 0) { throw 'Frontend configuration could not be read.' }
    $frontendConfig = $frontendJson | ConvertFrom-Json
    if ($frontendConfig.apiUrl.TrimEnd('/') -notin @('http://127.0.0.1:8000', 'http://localhost:8000')) {
        throw 'Frontend NEXT_PUBLIC_API_BASE_URL must point to http://127.0.0.1:8000.'
    }
    if ($bridgeConfig.host -notin @('127.0.0.1', 'localhost') -or $bridgeConfig.port -lt 1 -or $bridgeConfig.port -gt 65535) {
        throw 'The launcher requires a bridge bound to 127.0.0.1 or localhost with a valid port.'
    }
    $bridgeUrl = 'http://{0}:{1}' -f $bridgeConfig.host, $bridgeConfig.port
    $configuredUrl = [uri]$backendConfig.url
    if ($configuredUrl.Host -notin @('127.0.0.1', 'localhost') -or $configuredUrl.Scheme -ne 'http' -or
        $configuredUrl.Port -ne $bridgeConfig.port -or $configuredUrl.AbsolutePath -ne '/') {
        throw 'Backend WHATSAPP_BRIDGE_URL must point to this local bridge and its configured port.'
    }
    if ($backendConfig.key -cne $bridgeConfig.apiKey) { throw 'The backend and bridge WHATSAPP_BRIDGE_API_KEY values must match.' }
    if ($backendConfig.origins -notcontains 'http://127.0.0.1:3000') { throw 'Backend CORS_ORIGINS must include http://127.0.0.1:3000.' }
    $headers = @{}
    if ($bridgeConfig.apiKey) { $headers['x-api-key'] = $bridgeConfig.apiKey }
    Invoke-Checked $node @('scripts/patch-wwebjs-media-id.cjs', '--check') $bridge
    Invoke-Checked $node @('scripts/patch-wwebjs-message-id.cjs', '--check') $bridge
    if ($CheckOnly) { Write-Host 'Preflight passed. No services started.'; exit 0 }
    $bridgeMarker = Join-Path $bridge 'dist\index.js'
    $bridgeBuild = Test-BuildNeeded $bridgeMarker @((Join-Path $bridge 'src'), (Join-Path $bridge 'package.json'),
        (Join-Path $bridge 'bun.lock'), (Join-Path $bridge 'tsconfig.json'), (Join-Path $bridge 'tsconfig.build.json'))
    if ($bridgeBuild -and !(Get-Listener $bridgeConfig.port)) {
        Write-Host 'Building WhatsApp bridge...'
        Invoke-Checked $node @('node_modules/typescript/bin/tsc', '-p', 'tsconfig.build.json') $bridge
    }
    $frontendMarker = Join-Path $frontend '.next\BUILD_ID'
    $frontendBuild = Test-BuildNeeded $frontendMarker @((Join-Path $frontend 'src'), (Join-Path $frontend 'package.json'),
        (Join-Path $frontend 'bun.lock'), (Join-Path $frontend '.env.local'), (Join-Path $frontend 'next.config.mjs'), (Join-Path $frontend 'tsconfig.json'))
    if ($frontendBuild -and !(Get-Listener 3000)) {
        Write-Host 'Building dashboard (first launch or source changed)...'
        Invoke-Checked $node @('node_modules/next/dist/bin/next', 'build') $frontend
    }
    Start-LocalService -Name 'bridge' -Port $bridgeConfig.port -Executable $node `
        -Arguments @('"' + $bridgeMarker + '"') -Directory $bridge -Url "$bridgeUrl/status" -Headers $headers `
        -Validate { param($r) $null -ne $r.generation -and $null -ne $r.status }
    Start-LocalService -Name 'backend' -Port 8000 -Executable $python `
        -Arguments @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -Directory $backend -Url 'http://127.0.0.1:8000/api/health' `
        -Validate { param($r) $r.database -eq 'ok' -and $r.worker -eq 'running' }
    Start-LocalService -Name 'frontend' -Port 3000 -Executable $node `
        -Arguments @('"' + (Join-Path $frontend 'node_modules\next\dist\bin\next') + '"', 'start', '--hostname', '127.0.0.1', '--port', '3000') `
        -Directory $frontend -Url 'http://127.0.0.1:3000/whatsapp-bill-sender' `
        -Validate { param($r) [string]$r -match 'Office document dashboard' }
    Start-LocalService -Name 'mobile' -Port 8002 -Executable $python `
        -Arguments @('-m', 'uvicorn', 'app.mobile_main:app', '--host', '127.0.0.1', '--port', '8002') `
        -Directory $backend -Url 'http://127.0.0.1:8002/health' `
        -Validate { param($r) $r.service -eq 'office-mobile' -and $r.manual_only -eq $true }
    Write-Host 'Office Dashboard is running. WhatsApp restores its saved session in the background.'
    Write-Host "Logs: $logs"
    if (!$NoBrowser) { Start-Process 'http://127.0.0.1:3000/whatsapp-bill-sender' }
} catch {
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Logs: $logs"
    exit 1
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
