$ErrorActionPreference = "Stop"
.\.venv\Scripts\python -m src.scanner
if ($LASTEXITCODE -ne 0) {
    throw "Scanner exited with code $LASTEXITCODE"
}
