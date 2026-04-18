param(
  [string]$OutputDir = ".\backups"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $OutputDir)) {
  New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFile = Join-Path $OutputDir "chainmonitor_$ts.sql"

$container = if ((docker ps --format "{{.Names}}" | Select-String -SimpleMatch "cm-postgres" | Measure-Object).Count -gt 0) {
  "cm-postgres"
}
elseif ((docker ps --format "{{.Names}}" | Select-String -SimpleMatch "cm-postgres-lite" | Measure-Object).Count -gt 0) {
  "cm-postgres-lite"
}
else {
  throw "No running postgres container found (cm-postgres or cm-postgres-lite)"
}

docker exec -t $container pg_dump -U cm -d chainmonitor > $backupFile
if ($LASTEXITCODE -ne 0) {
  throw "pg_dump failed"
}

Write-Host "Done: backup created at $backupFile"
