#requires -Version 5.1
<# RAiF 10.1: only Windows, Git and local deterministic validation. No provider calls. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Demo','Prepare','Review')][string]$Mode,
    [string]$Repository = (Split-Path $PSScriptRoot -Parent),
    [string]$PinSha,
    [string]$OutputRoot = (Join-Path $env:LOCALAPPDATA 'Rassvet_AI_Fabric\worktree_review'),
    [string[]]$AllowPaths = @(),
    [string]$RunDir
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows)) {
    throw 'WINDOWS_ONLY'
}
if ($Mode -ne 'Review' -and $PinSha -notmatch '^[0-9a-fA-F]{40}$') { throw 'PIN_SHA_REQUIRED' }
if ($Mode -eq 'Prepare' -and $AllowPaths.Count -eq 0) { throw 'ALLOWLIST_REQUIRED' }
if ($Mode -eq 'Review' -and [string]::IsNullOrWhiteSpace($RunDir)) { throw 'RUN_DIR_REQUIRED' }
$entry = Join-Path (Split-Path $PSScriptRoot -Parent) 'src\rai_fabric\worktree_review.py'
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw 'OFFLINE_REVIEW_MODULE_MISSING' }
# Verify an actual CPython runtime, not the WindowsApps store placeholder.
# The previous live-turn milestone already encountered WindowsApps aliases.
$interpreters = New-Object 'System.Collections.Generic.List[object]'
$pyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
if ($null -ne $pyLauncher) {
    $interpreters.Add(@{ Exe = $pyLauncher.Source; Prefix = @('-3') })
}
$pythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
if ($null -ne $pythonCommand -and $pythonCommand.Source -notmatch '(?i)[\\/]WindowsApps[\\/]') {
    $interpreters.Add(@{ Exe = $pythonCommand.Source; Prefix = @() })
}
$pythonDir = Join-Path $env:LOCALAPPDATA 'Programs\Python'
if (Test-Path -LiteralPath $pythonDir -PathType Container) {
    foreach ($candidate in @(Get-ChildItem -LiteralPath $pythonDir -Filter 'Python3*' -Directory -ErrorAction SilentlyContinue)) {
        $exePath = Join-Path $candidate.FullName 'python.exe'
        if (Test-Path -LiteralPath $exePath -PathType Leaf) {
            $interpreters.Add(@{ Exe = $exePath; Prefix = @() })
        }
    }
}
$selected = $null
foreach ($candidate in $interpreters) {
    try {
        $probeArgs = @($candidate.Prefix) + @('-I','-B','-c',
            'import sys; raise SystemExit(0 if sys.platform == "win32" and sys.version_info >= (3, 11) else 2)')
        & $candidate.Exe @probeArgs 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $selected = $candidate; break }
    } catch { continue }
}
if ($null -eq $selected) { throw 'PYTHON_311_REAL_BINARY_NOT_FOUND' }
$oldPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH','Process')
$oldPythonNoUser = [Environment]::GetEnvironmentVariable('PYTHONNOUSERSITE','Process')
$oldPythonUTF8 = [Environment]::GetEnvironmentVariable('PYTHONUTF8','Process')
try {
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONUTF8 = '1'
    $cli = @('-I','-B',$entry)
    switch ($Mode) {
        'Demo' { $cli += @('demo','--repo',$Repository,'--pin',$PinSha,'--output-root',$OutputRoot) }
        'Prepare' {
            $cli += @('prepare','--repo',$Repository,'--pin',$PinSha,'--output-root',$OutputRoot)
            foreach ($path in $AllowPaths) { $cli += @('--allow',$path) }
        }
        'Review' { $cli += @('review','--run',$RunDir) }
    }
    $execArgs = @($selected.Prefix) + $cli
    & $selected.Exe @execArgs
    if ($LASTEXITCODE -ne 0) { throw "SAFE_WORKTREE_REVIEW_BLOCKED (exit=$LASTEXITCODE)" }
} finally {
    [Environment]::SetEnvironmentVariable('PYTHONPATH',$oldPythonPath,'Process')
    [Environment]::SetEnvironmentVariable('PYTHONNOUSERSITE',$oldPythonNoUser,'Process')
    [Environment]::SetEnvironmentVariable('PYTHONUTF8',$oldPythonUTF8,'Process')
}
