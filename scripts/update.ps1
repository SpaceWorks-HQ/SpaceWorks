<# Production update entry point. #>
[CmdletBinding()]
param([switch]$Force)
throw "Production updates require the Linux host operation lock. Run 'bash scripts/update.sh --force' inside WSL2 or on the Linux server."
