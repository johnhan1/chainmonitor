$ErrorActionPreference = "Stop"

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "Please run scripts/setup.ps1 first to create the local .venv"
}

& $venvPython -c "from src.app.services.bsc_pipeline import BscPipelineService; print(BscPipelineService().run_once().model_dump())"
if ($LASTEXITCODE -ne 0) {
  throw "BSC pipeline run-once failed"
}

Write-Host "Done: BSC run-once executed"
