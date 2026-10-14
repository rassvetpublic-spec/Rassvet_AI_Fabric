# Развёртывание и управление фоновой службой диспетчера задач Rassvet AI Fabric (Stage R0.5).
[CmdletBinding()]
param(
    [ValidateSet("Install", "Uninstall", "Status", "Start", "Stop")]
    [string]$Action = "Status",

    [string]$TaskName = "RassvetWorkerFleetService",
    [string]$DbPath = "",
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'resolve-python.ps1')

if (-not $DbPath) {
    $DbPath = Join-Path $repoRoot '.rai-fabric\state.sqlite3'
}

$selection = Resolve-RAiFPython
$pythonExe = [string]$selection.FilePath

Write-Host "=== Rassvet AI Fabric Worker Fleet Service (R0.5) ===" -ForegroundColor Cyan
Write-Host "Action:      $Action"
Write-Host "Task/Svc:    $TaskName"
Write-Host "Python:      $pythonExe"
Write-Host "Repo Root:   $repoRoot"
Write-Host "DB Path:     $DbPath"
Write-Host "-----------------------------------------------------"

switch ($Action) {
    "Status" {
        $previous = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
        try {
            $env:PYTHONPATH = Join-Path $repoRoot 'src'
            & $pythonExe -m rai_fabric.service_runner --status --db-path $DbPath
        } finally {
            [Environment]::SetEnvironmentVariable('PYTHONPATH', $previous, 'Process')
        }
        $schtasksQuery = schtasks /query /tn $TaskName 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Scheduled Task Status: INSTALLED" -ForegroundColor Green
        } else {
            Write-Host "Scheduled Task Status: NOT_REGISTERED" -ForegroundColor Yellow
        }
    }
    "Install" {
        if ($DryRun) {
            Write-Host "[DryRun] Would register scheduled task '$TaskName' to run at logon/startup." -ForegroundColor Yellow
            return
        }
        $argList = "-m rai_fabric.service_runner --daemon --db-path `"$DbPath`""
        $actionCmd = "`"$pythonExe`""
        $cmd = "schtasks /create /tn `"$TaskName`" /tr `"$actionCmd $argList`" /sc ONLOGON /rl HIGHEST /f"
        Invoke-Expression $cmd
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Task '$TaskName' successfully registered." -ForegroundColor Green
        } else {
            Write-Warning "Failed to register scheduled task ($LASTEXITCODE)."
        }
    }
    "Uninstall" {
        if ($DryRun) {
            Write-Host "[DryRun] Would unregister scheduled task '$TaskName'." -ForegroundColor Yellow
            return
        }
        $previous = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
        try {
            $env:PYTHONPATH = Join-Path $repoRoot 'src'
            & $pythonExe -m rai_fabric.service_runner --stop --db-path $DbPath 2>$null
        } finally {
            [Environment]::SetEnvironmentVariable('PYTHONPATH', $previous, 'Process')
        }
        schtasks /delete /tn $TaskName /f 2>$null
        Write-Host "Task '$TaskName' successfully uninstalled." -ForegroundColor Green
    }
    "Start" {
        if ($DryRun) {
            Write-Host "[DryRun] Would start task '$TaskName'." -ForegroundColor Yellow
            return
        }
        schtasks /run /tn $TaskName
        Start-Sleep -Seconds 1
        $previous = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
        try {
            $env:PYTHONPATH = Join-Path $repoRoot 'src'
            & $pythonExe -m rai_fabric.service_runner --status --db-path $DbPath
        } finally {
            [Environment]::SetEnvironmentVariable('PYTHONPATH', $previous, 'Process')
        }
    }
    "Stop" {
        if ($DryRun) {
            Write-Host "[DryRun] Would stop task '$TaskName' and service." -ForegroundColor Yellow
            return
        }
        $previous = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
        try {
            $env:PYTHONPATH = Join-Path $repoRoot 'src'
            & $pythonExe -m rai_fabric.service_runner --stop --db-path $DbPath
        } finally {
            [Environment]::SetEnvironmentVariable('PYTHONPATH', $previous, 'Process')
        }
        schtasks /end /tn $TaskName 2>$null
    }
}
