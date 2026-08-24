<# Apply the newest fully-published Space Works release to production Compose. #>
[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

throw "The H1 production updater requires the Linux Compose wrapper. Run scripts/update.sh inside WSL2."

$compose = @("compose", "-f", "docker-compose.prod.yml")
$lockPath = Join-Path $root ".spaceworks-update.lock"
$versionPath = Join-Path $root ".spaceworks-version"
$backupDir = Join-Path $root "backups"
$releaseApi = "https://api.github.com/repos/SpaceWorks-HQ/SpaceWorks/releases/latest"
$utf8 = [Text.UTF8Encoding]::new($false)
$lock = $null
$claimed = $false
$completed = $false
$deploymentStarted = $false
$current = ""
$previousTag = [Environment]::GetEnvironmentVariable("MAKERSPACE_IMAGE_TAG", "Process")

function Say([string]$message) { Write-Host "[Space Works updater] $message" }
function Assert-DockerSuccess([string]$message) {
  if ($LASTEXITCODE -ne 0) { throw $message }
}
function Wait-BackendReady {
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    docker @compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/readiness/', timeout=3).read()" *> $null
    if ($LASTEXITCODE -eq 0) { return $true }
    Start-Sleep -Seconds 3
  }
  return $false
}
function Invoke-ApplicationRollback([string]$version) {
  Say "Update failed; rolling application containers back to $version."
  $env:MAKERSPACE_IMAGE_TAG = $version
  docker @compose pull migrate backend worker beat frontend | Out-Host
  if ($LASTEXITCODE -ne 0) { Say "Could not refresh previous images; trying the host's cached copies." }
  docker @compose up -d | Out-Host
  if ($LASTEXITCODE -ne 0) { return $false }
  if (-not (Wait-BackendReady)) { return $false }
  Say "Rollback complete: $version is healthy."
  return $true
}

try {
  try {
    $lock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::Write, [IO.FileShare]::None)
  }
  catch [IO.IOException] {
    Say "Another update is already running; skipping."
    exit 0
  }

  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker is not installed." }
  docker info *> $null
  Assert-DockerSuccess "Docker is not running."

  $headers = @{ Accept = "application/vnd.github+json"; "User-Agent" = "spaceworks-self-host-updater" }
  $release = Invoke-RestMethod -Uri $releaseApi -Headers $headers
  $version = ([string]$release.tag_name) -replace '^v', ''
  if ($version -notmatch '^\d+\.\d+\.\d+-main\.\d+\.[0-9a-f]{12}$') {
    throw "GitHub latest release returned an unexpected tag: $($release.tag_name)"
  }

  $current = if (Test-Path $versionPath) { (Get-Content -Raw $versionPath).Trim() } else { "" }
  $claimArgs = @("--current=$current", "--available=$version")
  if ($Force) { $claimArgs += "--force" }
  $decisionOutput = docker @compose run --rm --no-deps -T backend --role management python manage.py update_control claim @claimArgs
  Assert-DockerSuccess "The running Space Works backend could not accept the update check."
  $decision = ([string[]]$decisionOutput)[-1].Trim()
  if ($decision -ne "run") {
    if ($current -eq $version) { Say "$version is already installed." }
    else { Say "$version is available; automatic updates are off and no manual update is queued." }
    return
  }
  $claimed = $true

  Say "Updating $(if ($current) { $current } else { 'untracked installation' }) to $version."
  $env:MAKERSPACE_IMAGE_TAG = $version
  New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
  docker @compose up -d --wait db
  Assert-DockerSuccess "PostgreSQL did not become ready for backup."
  $backupName = "pre-update-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')).sql.gz"
  Say "Creating database backup backups/$backupName."
  $backupCommand = 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip -c > "/backups/' + $backupName + '"'
  docker @compose exec -T db sh -c $backupCommand
  Assert-DockerSuccess "Database backup failed; update cancelled."
  docker @compose exec -T db test -s "/backups/$backupName"
  Assert-DockerSuccess "Database backup was empty; update cancelled."
  docker @compose run --rm --no-deps -T backend --role management python manage.py update_control record-backup --name $backupName *> $null
  Assert-DockerSuccess "The database backup was created but its status could not be recorded."

  Say "Pulling immutable release images."
  docker @compose pull migrate backend worker beat frontend
  Assert-DockerSuccess "Could not pull release images; update cancelled."

  Say "Running migrations and replacing application containers."
  $deploymentStarted = $true
  docker @compose up -d
  Assert-DockerSuccess "Compose could not deploy release $version."

  if (-not (Wait-BackendReady)) { throw "Release $version did not become ready. The backup is backups/$backupName." }

  [IO.File]::WriteAllText($versionPath, "$version`n", $utf8)
  docker @compose run --rm --no-deps -T backend --role management python manage.py update_control complete --version $version *> $null
  Assert-DockerSuccess "Release $version is running but its status could not be recorded."
  $completed = $true
  Get-ChildItem -LiteralPath $backupDir -Filter "pre-update-*.sql.gz" -File |
    Where-Object LastWriteTimeUtc -lt (Get-Date).ToUniversalTime().AddDays(-14) |
    Remove-Item -Force
  Say "Update complete: $version."
}
catch {
  $updateError = $_
  $failureMessage = "Host update failed. Check backups/auto-update.log."
  if ($claimed -and -not $completed) {
    if ($deploymentStarted -and $current -match '^\d+\.\d+\.\d+-main\.\d+\.[0-9a-f]{12}$') {
      try { $rolledBack = Invoke-ApplicationRollback $current }
      catch { $rolledBack = $false }
      if ($rolledBack) {
        $failureMessage = "Update failed; application containers rolled back to $current. The database backup was retained."
      }
      else {
        Say "ERROR: automatic rollback to $current failed."
        $failureMessage = "Update and automatic rollback failed. Restore the database backup and previous image tag manually."
      }
    }
    docker @compose run --rm --no-deps -T backend --role management python manage.py update_control fail --message $failureMessage *> $null
  }
  throw $updateError
}
finally {
  if ($null -eq $previousTag) { Remove-Item Env:MAKERSPACE_IMAGE_TAG -ErrorAction SilentlyContinue }
  else { $env:MAKERSPACE_IMAGE_TAG = $previousTag }
  if ($lock) {
    $lock.Dispose()
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
  }
}
