<#
  Space Works - Open Source Makerspace Manager first-run setup for self-hosting (Windows).
  Right-click -> "Run with PowerShell", or run:  powershell -ExecutionPolicy Bypass -File setup.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

throw "Production host orchestration requires Linux flock and Unix-socket semantics. Run 'bash setup.sh' inside WSL2 instead."
