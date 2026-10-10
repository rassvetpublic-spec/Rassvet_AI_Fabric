# Run tests with a verified Python runtime; never rely on WindowsApps aliases.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-python.ps1')
$selection = Resolve-RAiFPython
$exe = $selection.FilePath
$prefix = @($selection.Prefix)
$root = Split-Path $PSScriptRoot -Parent
$env:PYTHONPATH = Join-Path $root 'src'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& $exe @prefix -m unittest discover -s (Join-Path $root 'tests') -v
if ($LASTEXITCODE -ne 0) {
    throw "Python tests failed: exit code $LASTEXITCODE"
}
Write-Host 'Windows Python tests passed.'
