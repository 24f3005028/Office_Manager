[CmdletBinding()]
param([switch]$StopOnly)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell

function New-OfficeShortcut([string]$Name, [string]$Target, [string]$Description, [int]$Icon) {
    $shortcutPath = Join-Path $desktop "$Name.lnk"
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $repo $Target
    $shortcut.WorkingDirectory = $repo
    $shortcut.Description = $Description
    $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,$Icon"
    $shortcut.Save()
    Write-Host "Created $shortcutPath"
}

if (!$StopOnly) {
    New-OfficeShortcut 'Office WhatsApp Sender' 'Start-Office.cmd' 'Start Office Dashboard services' 14
}
New-OfficeShortcut 'Stop Office Dashboard' 'Stop-Office.cmd' 'Stop Office Dashboard services and its Cloudflare tunnel' 27
