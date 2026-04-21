$ErrorActionPreference = "Stop"

param(
  [string]$ReportPath = ".artifacts/ai-review-repair/report.json",
  [string]$SummaryPath = ".artifacts/ai-review-repair/summary.md"
)

function Get-VenvPython {
  $windowsVenvPython = ".\.venv\Scripts\python.exe"
  $unixVenvPython = "./.venv/bin/python"

  if (Test-Path $windowsVenvPython) {
    return $windowsVenvPython
  }

  if (Test-Path $unixVenvPython) {
    return $unixVenvPython
  }

  throw "Cannot find local .venv python. Expected one of: $windowsVenvPython or $unixVenvPython"
}

function Invoke-GateCheck {
  param(
    [string]$PythonPath,
    [hashtable]$Gate
  )

  $timer = [System.Diagnostics.Stopwatch]::StartNew()
  $output = & $PythonPath @($Gate.args) 2>&1
  $exitCode = $LASTEXITCODE
  $timer.Stop()

  $evidence = ($output | Select-Object -Last 20) -join "`n"
  if ([string]::IsNullOrWhiteSpace($evidence)) {
    $evidence = "<no output>"
  }

  return [ordered]@{
    name = $Gate.name
    passed = ($exitCode -eq 0)
    exit_code = $exitCode
    duration_ms = [int]$timer.ElapsedMilliseconds
    evidence = $evidence
  }
}

$traceId = ([guid]::NewGuid()).ToString("N")
$startedAt = (Get-Date).ToUniversalTime().ToString("o")
$pythonPath = Get-VenvPython

$gates = @(
  @{ name = "lint"; args = @("-m", "ruff", "check", "src", "tests") },
  @{ name = "test"; args = @("-m", "pytest", "-q") }
)

$checkResults = @()
foreach ($gate in $gates) {
  $checkResults += Invoke-GateCheck -PythonPath $pythonPath -Gate $gate
}

$totalCount = $checkResults.Count
$passedCount = ($checkResults | Where-Object { $_.passed }).Count
$failedChecks = $checkResults | Where-Object { -not $_.passed } | ForEach-Object { $_.name }
$passRate = 0.0
if ($totalCount -gt 0) {
  $passRate = [Math]::Round(($passedCount * 100.0) / $totalCount, 2)
}

$failureDistribution = [ordered]@{}
foreach ($check in $checkResults | Where-Object { -not $_.passed }) {
  if (-not $failureDistribution.Contains($check.name)) {
    $failureDistribution[$check.name] = 0
  }
  $failureDistribution[$check.name] += 1
}

$status = if ($passedCount -eq $totalCount) { "passed" } else { "failed" }
$reportObject = [ordered]@{
  status = $status
  trace_id = $traceId
  checks = $checkResults
  summary = [ordered]@{
    rounds_used = 1
    hard_gates_passed = ($status -eq "passed")
    hard_gate_pass_rate = $passRate
    total_checks = $totalCount
    passed_checks = $passedCount
    failed_checks = $failedChecks
  }
  observability = [ordered]@{
    rounds = 1
    pass_rate = $passRate
    failure_reason_distribution = $failureDistribution
    generated_at_utc = $startedAt
  }
}

$reportDirectory = Split-Path -Parent $ReportPath
if (-not [string]::IsNullOrWhiteSpace($reportDirectory)) {
  New-Item -Path $reportDirectory -ItemType Directory -Force | Out-Null
}

$summaryDirectory = Split-Path -Parent $SummaryPath
if (-not [string]::IsNullOrWhiteSpace($summaryDirectory)) {
  New-Item -Path $summaryDirectory -ItemType Directory -Force | Out-Null
}

$reportObject | ConvertTo-Json -Depth 8 | Set-Content -Path $ReportPath -Encoding UTF8

$summaryLines = @(
  "# AI Review Repair CI Summary",
  "",
  "- trace_id: $traceId",
  "- rounds: 1",
  "- pass_rate: $passRate%",
  "- failed_checks: $($failedChecks -join ', ')",
  "",
  "## Failure Reason Distribution",
  ""
)

if ($failureDistribution.Count -eq 0) {
  $summaryLines += "- none"
}
else {
  foreach ($entry in $failureDistribution.GetEnumerator()) {
    $summaryLines += "- $($entry.Key): $($entry.Value)"
  }
}

$summaryContent = $summaryLines -join "`n"
Set-Content -Path $SummaryPath -Value $summaryContent -Encoding UTF8

if ($env:GITHUB_STEP_SUMMARY) {
  Add-Content -Path $env:GITHUB_STEP_SUMMARY -Value $summaryContent
}

if ($env:GITHUB_ENV) {
  Add-Content -Path $env:GITHUB_ENV -Value "AI_REVIEW_TRACE_ID=$traceId"
}

if ($env:GITHUB_OUTPUT) {
  Add-Content -Path $env:GITHUB_OUTPUT -Value "trace_id=$traceId"
  Add-Content -Path $env:GITHUB_OUTPUT -Value "report_path=$ReportPath"
  Add-Content -Path $env:GITHUB_OUTPUT -Value "summary_path=$SummaryPath"
}

if ($status -ne "passed") {
  throw "AI review gate blocked, trace_id=$traceId, failed_checks=$($failedChecks -join ',')"
}

Write-Host "AI review gate passed, trace_id=$traceId"
