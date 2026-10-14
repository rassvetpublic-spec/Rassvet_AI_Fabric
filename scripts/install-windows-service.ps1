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
        $workingDir = Join-Path $repoRoot 'src'
        $argList = "-m rai_fabric.service_runner --daemon --db-path `"$DbPath`""
        $registered = $false

        try {
            $taskAction = New-ScheduledTaskAction -Execute $pythonExe -Argument $argList -WorkingDirectory $workingDir
            $userPrincipal = if ([string]::IsNullOrWhiteSpace($env:USERDOMAIN)) { $env:USERNAME } else { "$($env:USERDOMAIN)\$($env:USERNAME)" }
            $taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $userPrincipal
            $taskObj = Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $taskTrigger -Description "Rassvet AI Fabric Worker Fleet Service (R0.5)" -Force -ErrorAction Stop
            if ($null -ne $taskObj) {
                $registered = $true
                Write-Host "Task '$TaskName' successfully registered in Windows Task Scheduler." -ForegroundColor Green
            }
        } catch {
            # Fallback to schtasks if Register-ScheduledTask fails
        }

        if (-not $registered) {
            $actionCmd = "`"$pythonExe`""
            $cmd = "schtasks /create /tn `"$TaskName`" /tr `"$actionCmd $argList`" /sc ONLOGON /f"
            $null = Invoke-Expression "$cmd 2>`$null"
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Task '$TaskName' successfully registered in Windows Task Scheduler." -ForegroundColor Green
            } else {
                Write-Host "Note: Non-elevated session. Schtasks registration requires Administrator elevation." -ForegroundColor Yellow
                Write-Host "User-mode background daemon execution enabled via Start-Process." -ForegroundColor Cyan
            }
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
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        schtasks /delete /tn $TaskName /f 2>$null
        Write-Host "Task '$TaskName' successfully uninstalled." -ForegroundColor Green
    }
    "Start" {
        if ($DryRun) {
            Write-Host "[DryRun] Would start task '$TaskName'." -ForegroundColor Yellow
            return
        }
        $schtasksQuery = schtasks /query /tn $TaskName 2>$null
        if ($LASTEXITCODE -eq 0) {
            schtasks /run /tn $TaskName
        } else {
            Write-Host "Starting background daemon directly via Start-Process (User-mode)..." -ForegroundColor Cyan
            $previous = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
            try {
                $env:PYTHONPATH = Join-Path $repoRoot 'src'
                $proc = Start-Process -FilePath $pythonExe -ArgumentList "-m rai_fabric.service_runner --daemon --db-path `"$DbPath`"" -WindowStyle Hidden -PassThru
                Write-Host "Daemon launched with PID: $($proc.Id)" -ForegroundColor Green
            } finally {
                [Environment]::SetEnvironmentVariable('PYTHONPATH', $previous, 'Process')
            }
        }
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
