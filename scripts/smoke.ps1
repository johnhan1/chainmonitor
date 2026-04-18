$ErrorActionPreference = "Stop"

function Test-Endpoint {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSec = 15
  )
  $resp = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSec
  if ($resp.StatusCode -lt 200 -or $resp.StatusCode -ge 300) {
    throw "Endpoint check failed: $Url status=$($resp.StatusCode)"
  }
}

Test-Endpoint -Url "http://localhost:8000/healthz"
Test-Endpoint -Url "http://localhost:8000/metrics"
Test-Endpoint -Url "http://localhost:9090/-/healthy"
Test-Endpoint -Url "http://localhost:3000/api/health"

Write-Host "Done: smoke checks passed"
