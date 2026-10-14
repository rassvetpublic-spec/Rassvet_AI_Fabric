# Демонстрация планировщика Stage R26 через PowerShell (4 параллельных воркера).
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-python.ps1')

$repoRoot = Split-Path $PSScriptRoot -Parent
$previous = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
try {
    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    $selection = Resolve-RAiFPython
    $exe = [string]$selection.FilePath
    $prefix = @($selection.Prefix)
    & $exe @prefix (Join-Path $PSScriptRoot 'demo-stage-r26-scheduler.py')
    if ($LASTEXITCODE -ne 0) { throw "Ошибка демонстрации планировщика: $LASTEXITCODE" }
} finally {
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $previous, 'Process')
}
