# RAiF 10.2C: интеграционный smoke с надёжным разрешением Python.
# Выполняется только в одноразовом извлечённом дереве под D:\ЗАГРУЗКИ.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-python.ps1')
$selection = Resolve-RAiFPython
$exe = $selection.FilePath
$prefix = @($selection.Prefix)
$oldPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH','Process')
$oldPythonUtf8 = [Environment]::GetEnvironmentVariable('PYTHONUTF8','Process')
$oldPythonIo = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING','Process')
try {
    $env:PYTHONPATH = Join-Path (Split-Path $PSScriptRoot -Parent) 'src'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $root = Join-Path $env:TEMP ('raif-10-2c-mock-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $db = Join-Path $root 'state.sqlite3'
    & $exe @prefix -X utf8 -B -m rai_fabric --db $db init
    if ($LASTEXITCODE -ne 0) { throw 'RAIF_SMOKE_INIT_FAILED' }
    & $exe @prefix -X utf8 -B -m rai_fabric --db $db submit --objective 'Офлайн проверка очереди' --provider mock --workspace $root
    if ($LASTEXITCODE -ne 0) { throw 'RAIF_SMOKE_SUBMIT_FAILED' }
    & $exe @prefix -X utf8 -B -m rai_fabric --db $db run-once --provider mock
    if ($LASTEXITCODE -ne 0) { throw 'RAIF_SMOKE_RUN_FAILED' }
    & $exe @prefix -X utf8 -B -m rai_fabric --db $db tasks
    if ($LASTEXITCODE -ne 0) { throw 'RAIF_SMOKE_TASKS_FAILED' }
    Write-Host 'RAIF_INTEGRATION_SMOKE_PASS'
} finally {
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $oldPythonPath, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONUTF8', $oldPythonUtf8, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', $oldPythonIo, 'Process')
}
