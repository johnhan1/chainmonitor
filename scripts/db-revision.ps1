param(
  [Parameter(Mandatory = $true)]
  [string]$Message
)

$ErrorActionPreference = "Stop"

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "Please run scripts/setup.ps1 first to create the local .venv"
}

& $venvPython -m alembic revision -m "$Message"
if ($LASTEXITCODE -ne 0) {
  throw "alembic revision failed"
}

Write-Host "Done: new migration revision created"
