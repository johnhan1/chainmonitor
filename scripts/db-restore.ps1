param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $BackupFile)) {
  throw "Backup file not found: $BackupFile"
}

$container = if ((docker ps --format "{{.Names}}" | Select-String -SimpleMatch "cm-postgres" | Measure-Object).Count -gt 0) {
  "cm-postgres"
}
elseif ((docker ps --format "{{.Names}}" | Select-String -SimpleMatch "cm-postgres-lite" | Measure-Object).Count -gt 0) {
  "cm-postgres-lite"
}
else {
  throw "No running postgres container found (cm-postgres or cm-postgres-lite)"
}

Get-Content $BackupFile | docker exec -i $container psql -U cm -d chainmonitor
if ($LASTEXITCODE -ne 0) {
  throw "psql restore failed"
}

Write-Host "Done: restored backup from $BackupFile"
