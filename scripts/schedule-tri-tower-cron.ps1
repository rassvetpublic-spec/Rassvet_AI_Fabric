# Развёртывание и управление регламентным расписанием аудита паритета Трёх Башен (Stage R26 / R0.4).
[CmdletBinding()]
param(
    [ValidateSet("Install", "Uninstall", "Status", "RunOnce")]
    [string]$Action = "RunOnce",

    [string]$TaskName = "RassvetTriTowerParityCron",
    [int]$IntervalHours = 1,
    [switch]$DryRun,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'resolve-python.ps1')

$selection = Resolve-RAiFPython
$pythonExe = [string]$selection.FilePath

if (-not $Json) {
    Write-Host "=== Rassvet AI Fabric Tri-Tower Parity Cron ===" -ForegroundColor Cyan
    Write-Host "Action:      $Action"
    Write-Host "Task Name:   $TaskName"
    Write-Host "Interval:    Every $IntervalHours hour(s)"
    Write-Host "Python:      $pythonExe"
    Write-Host "Repo Root:   $repoRoot"
    Write-Host "-----------------------------------------------"
}

switch ($Action) {
    "RunOnce" {
        $previous = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
        try {
            $env:PYTHONPATH = Join-Path $repoRoot 'src'
            $jsonFlag = if ($Json) { "--json" } else { "" }
            & $pythonExe -m rai_fabric.parity_cron --once $jsonFlag
        } finally {
            [Environment]::SetEnvironmentVariable('PYTHONPATH', $previous, 'Process')
        }
    }
    "Status" {
        $schtasksQuery = schtasks /query /tn $TaskName 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Scheduled Task Status: INSTALLED" -ForegroundColor Green
            schtasks /query /tn $TaskName /fo LIST /v
        } else {
            Write-Host "Scheduled Task Status: NOT_REGISTERED" -ForegroundColor Yellow
        }
    }
    "Install" {
        if ($DryRun) {
            Write-Host "[DryRun] Would register scheduled task '$TaskName' to run every $IntervalHours hour(s)." -ForegroundColor Yellow
            return
        }
        $workingDir = Join-Path $repoRoot 'src'
        $argList = "-m rai_fabric.parity_cron --once"
        $registered = $false

        try {
            $taskAction = New-ScheduledTaskAction -Execute $pythonExe -Argument $argList -WorkingDirectory $workingDir
            $userPrincipal = if ([string]::IsNullOrWhiteSpace($env:USERDOMAIN)) { $env:USERNAME } else { "$($env:USERDOMAIN)\$($env:USERNAME)" }
            $taskTrigger = New-ScheduledTaskTrigger -Daily -At "00:00"
            $taskObj = Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $taskTrigger -Description "Rassvet AI Fabric Tri-Tower Parity Cron (R26)" -Force -ErrorAction Stop
            if ($taskObj) {
                $registered = $true
            }
        } catch {
            Write-Warning "PowerShell Register-ScheduledTask failed ($($_.Exception.Message)). Falling back to schtasks.exe..."
        }

        if (-not $registered) {
            $escapedPy = "`"$pythonExe`""
            $fullCmd = "$escapedPy -m rai_fabric.parity_cron --once"
            schtasks /create /tn $TaskName /tr $fullCmd /sc hourly /mo $IntervalHours /f
        }

        Write-Host "Scheduled Task '$TaskName' successfully registered!" -ForegroundColor Green
    }
    "Uninstall" {
        if ($DryRun) {
            Write-Host "[DryRun] Would unregister scheduled task '$TaskName'." -ForegroundColor Yellow
            return
        }
        schtasks /delete /tn $TaskName /f 2>$null
        Write-Host "Scheduled Task '$TaskName' unregistered." -ForegroundColor Green
    }
}
