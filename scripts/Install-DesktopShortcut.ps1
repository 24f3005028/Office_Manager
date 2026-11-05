$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Office WhatsApp Sender.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $repo 'Start-Office.cmd'
$shortcut.WorkingDirectory = $repo
$shortcut.Description = 'Start Office Dashboard backend, frontend and WhatsApp bridge'
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,14"
$shortcut.Save()
Write-Host "Created $shortcutPath"
