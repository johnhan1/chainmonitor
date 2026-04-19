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

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "Please run scripts/setup.ps1 first to create the local .venv"
}

Invoke-CheckedCommand "$venvPython -m pytest -q tests/test_phase2_backtest_gate2.py tests/test_phase2_full_features.py"
Write-Host "Done: Phase2-Full checks passed"
