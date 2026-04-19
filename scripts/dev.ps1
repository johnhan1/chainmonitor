param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("init", "up", "up-lite", "down", "reset", "migrate", "check", "smoke", "bsc-run-once", "backup", "restore", "status", "phase2-full-check", "all")]
  [string]$Command,
  [string]$BackupFile = ""
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
  param([string]$Cmd)
  Invoke-Expression $Cmd
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed: $Cmd"
  }
}

$fullCompose = "docker compose -f deploy\docker-compose.yml"
$liteCompose = "docker compose -f deploy\docker-compose.lite.yml"

switch ($Command) {
  "init" {
    Invoke-Checked ".\scripts\setup.ps1"
  }
  "up" {
    Invoke-Checked "$fullCompose up -d --build"
  }
  "up-lite" {
    Invoke-Checked "$liteCompose up -d --build"
  }
  "down" {
    Invoke-Checked "$fullCompose down"
    Invoke-Checked "$liteCompose down"
  }
  "reset" {
    Invoke-Checked "$fullCompose down -v"
    Invoke-Checked "$liteCompose down -v"
    Invoke-Checked "$fullCompose up -d --build"
  }
  "migrate" {
    Invoke-Checked ".\scripts\db-upgrade.ps1"
  }
  "check" {
    Invoke-Checked ".\scripts\check.ps1"
  }
  "smoke" {
    Invoke-Checked ".\scripts\smoke.ps1"
  }
  "bsc-run-once" {
    Invoke-Checked ".\scripts\bsc-run-once.ps1"
  }
  "backup" {
    Invoke-Checked ".\scripts\db-backup.ps1"
  }
  "restore" {
    if ([string]::IsNullOrWhiteSpace($BackupFile)) {
      throw "restore requires -BackupFile"
    }
    Invoke-Checked ".\scripts\db-restore.ps1 -BackupFile '$BackupFile'"
  }
  "status" {
    Invoke-Checked "$fullCompose ps"
  }
  "phase2-full-check" {
    Invoke-Checked ".\scripts\phase2-full-check.ps1"
  }
  "all" {
    Invoke-Checked ".\scripts\setup.ps1"
    Invoke-Checked "$fullCompose up -d --build"
    Invoke-Checked ".\scripts\db-upgrade.ps1"
    Invoke-Checked ".\scripts\bsc-run-once.ps1"
    Invoke-Checked ".\scripts\check.ps1"
    Invoke-Checked ".\scripts\smoke.ps1"
  }
}

Write-Host "Done: $Command"
