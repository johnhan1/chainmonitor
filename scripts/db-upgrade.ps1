$ErrorActionPreference = "Stop"

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "Please run scripts/setup.ps1 first to create the local .venv"
}

& $venvPython -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
  throw "alembic upgrade failed"
}

Write-Host "Done: database upgraded to the latest revision"
