[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$mutex = New-Object System.Threading.Mutex($false, 'Local\OfficeDocumentDashboardLauncher')
$ownsMutex = $false
$services = @(
    @{ Name = 'Cloudflare tunnel'; Executable = 'cloudflared.exe'; Path = 'data\cloudflare\cloudflared.exe'; Arguments = '\btunnel\b' }
    @{ Name = 'Frontend'; Executable = 'node.exe'; Path = 'frontend\node_modules\next\dist\bin\next'; Arguments = '\bstart\b.*--port\s+3000\b' }
    @{ Name = 'Mobile gateway'; Executable = 'python.exe'; Path = 'backend\.venv\Scripts\python.exe'; Arguments = '-m\s+uvicorn\s+app\.mobile_main:app\b' }
    @{ Name = 'Backend'; Executable = 'python.exe'; Path = 'backend\.venv\Scripts\python.exe'; Arguments = '-m\s+uvicorn\s+app\.main:app\b' }
    @{ Name = 'WhatsApp bridge'; Executable = 'node.exe'; Path = 'whatsapp-bridge\dist\index.js'; Arguments = '' }
)

try {
    try { $ownsMutex = $mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (!$ownsMutex) { throw 'Office Dashboard is starting or stopping. Try again once it finishes.' }

    $processes = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe' OR Name = 'node.exe' OR Name = 'python.exe'"
    $failed = @()
    foreach ($service in $services) {
        $path = [regex]::Escape((Join-Path $repo $service.Path))
        $matchesForService = @($processes | Where-Object {
            $_.Name -eq $service.Executable -and
            $_.CommandLine -match "(?:^|[\s`"])$path(?:[\s`"]|$)" -and
            $_.CommandLine -match $service.Arguments
        })
        foreach ($process in $matchesForService) {
            if ($process.ParentProcessId -in $matchesForService.ProcessId) { continue }
            if (!$PSCmdlet.ShouldProcess($service.Name, 'Stop process tree')) { continue }
            $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.ProcessId)"
            if (!$current -or $current.CreationDate -ne $process.CreationDate) { continue }
            & "$env:SystemRoot\System32\taskkill.exe" /PID $process.ProcessId /T /F
            if ($LASTEXITCODE -ne 0 -and (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue)) {
                $failed += $service.Name
            }
        }
        if (!$matchesForService) { Write-Host "$($service.Name) is already stopped." }
    }
    if ($failed) { throw "Could not stop $($failed -join ', ')." }
    if (!$WhatIfPreference) { Write-Host 'Office Dashboard services stopped.' }
} catch {
    Write-Host "Shutdown failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
