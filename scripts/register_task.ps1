$ErrorActionPreference = "Stop"

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot ".."))
$runner = Join-Path $projectDir "scripts\run_dashboard.cmd"
$taskName = "OfficeHubDashboard"

if (-not (Test-Path -LiteralPath $runner)) {
    throw "Runner not found: $runner"
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$runner`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Starts the local Office Hub dashboard." -Force
Write-Host "Registered $taskName for the current user."
