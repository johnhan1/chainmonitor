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

Invoke-CheckedCommand "$venvPython -m ruff check src tests"
Invoke-CheckedCommand "$venvPython -m pytest -q"

$hasGitDir = Test-Path ".git"
$hasGitCli = $null -ne (Get-Command git -ErrorAction SilentlyContinue)
if ($hasGitDir -and $hasGitCli) {
  Invoke-CheckedCommand "$venvPython -m pre_commit run --all-files"
}
else {
  Write-Host "Skip pre-commit: git is not installed or current directory is not a Git repository"
}

Write-Host "Done: lint + test passed"
