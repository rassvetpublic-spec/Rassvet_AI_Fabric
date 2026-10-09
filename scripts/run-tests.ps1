$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path (Split-Path $PSScriptRoot -Parent) 'src'
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m unittest discover -s (Join-Path (Split-Path $PSScriptRoot -Parent) 'tests') -v
} else {
    & python -m unittest discover -s (Join-Path (Split-Path $PSScriptRoot -Parent) 'tests') -v
}
