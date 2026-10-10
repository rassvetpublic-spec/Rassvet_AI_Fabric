# RAiF integrated Windows test runner: preserve original PowerShell contract.
# Only the temporary integration projection receives this candidate.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$oldPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
$oldPythonUTF8 = [Environment]::GetEnvironmentVariable('PYTHONUTF8', 'Process')
$oldPythonIO = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
try {
    $env:PYTHONPATH = Join-Path $root 'src'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $choice = $null

    # An actual runnable Python is preferred over a WindowsApps alias.
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand -and $pythonCommand.CommandType -eq 'Application' -and
        $pythonCommand.Source -notmatch '(?i)[\\/]WindowsApps[\\/]') {
        try {
            & $pythonCommand.Source -X utf8 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 2)' 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $choice = @{ FilePath = $pythonCommand.Source; Prefix = @() }
            }
        } catch { $choice = $null }
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if (-not $choice -and $pyCommand -and $pyCommand.CommandType -eq 'Application') {
        try {
            & $pyCommand.Source -3 -X utf8 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 2)' 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $choice = @{ FilePath = $pyCommand.Source; Prefix = @('-3') }
            }
        } catch { $choice = $null }
    }
    if (-not $choice) { throw 'Python 3.11+ was not found as a running executable.' }

    $exe = $choice.FilePath
    $prefix = @($choice.Prefix)
    & $exe @prefix -X utf8 -m unittest discover -s (Join-Path $root 'tests') -v
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed: exit code $LASTEXITCODE" }
    Write-Host 'Windows Python tests passed.'
} finally {
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $oldPythonPath, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONUTF8', $oldPythonUTF8, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', $oldPythonIO, 'Process')
}
