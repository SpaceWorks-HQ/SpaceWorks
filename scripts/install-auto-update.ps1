$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

throw "H1 automatic updates require the Linux host operation lock. Install scripts/install-auto-update.sh inside WSL2."
$updater = Join-Path $PSScriptRoot "update.ps1"
$taskName = "SpaceWorks Automatic Production Update"
$compose = @("compose", "-f", "docker-compose.prod.yml")

if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
  throw "Windows Task Scheduler cmdlets are unavailable. Schedule scripts/update.ps1 every seven days."
}

docker @compose run --rm --no-deps -T backend --role management python manage.py update_control set-auto on *> $null
if ($LASTEXITCODE -ne 0) { throw "The running Space Works backend could not enable automatic updates." }

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$updater`"" `
  -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger `
  -Once `
  -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Days 7)
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
  -TaskName $taskName `
  -Description "Checks GitHub Releases every seven days and safely updates Space Works production." `
  -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Automatic Space Works updates are enabled and checked every seven days."
