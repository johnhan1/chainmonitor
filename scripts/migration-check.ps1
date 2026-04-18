$ErrorActionPreference = "Stop"

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "Please run scripts/setup.ps1 first to create the local .venv"
}

$dbPath = ".\ci_migration_local.db"
$env:CM_POSTGRES_DSN = "sqlite+pysqlite:///$dbPath"

& $venvPython -m alembic downgrade base
if ($LASTEXITCODE -ne 0) {
  throw "alembic downgrade base failed"
}

& $venvPython -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
  throw "alembic upgrade head failed"
}

Write-Host "Done: migration chain check passed"
