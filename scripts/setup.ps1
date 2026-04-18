param(
  [string]$Python = "py -3.12"
)

$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
  param(
    [string]$Command
  )
  Invoke-Expression $Command
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed: $Command"
  }
}

if (-not (Test-Path ".venv")) {
  Invoke-CheckedCommand "$Python -m venv .venv"
}

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "Virtualenv Python not found: $venvPython"
}

$versionOutput = & $venvPython --version
if ($versionOutput -notmatch "Python 3\.1(1|2)\.") {
  throw "Unsupported .venv Python version (need 3.11 or 3.12): $versionOutput. Delete .venv and retry: .\scripts\setup.ps1 -Python 'py -3.12'"
}

Invoke-CheckedCommand "$venvPython -m pip install --upgrade pip"
Invoke-CheckedCommand "$venvPython -m pip install -r .\requirements\dev.txt"

if (Test-Path ".git") {
  Invoke-CheckedCommand "$venvPython -m pre_commit install"
}

Write-Host "Done: local .venv is ready ($versionOutput)"
