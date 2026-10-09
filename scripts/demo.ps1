# Однократная локальная демонстрация в отдельном каталоге. Без облачных моделей и изменений профилей Codex/BPR40.
$ErrorActionPreference = 'Stop'
$python = (Get-Command py -ErrorAction SilentlyContinue)
if ($python) { $exe = 'py'; $prefix = @('-3') }
else { $exe = 'python'; $prefix = @() }
$root = Join-Path $env:TEMP ('rai-fabric-demo-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $root | Out-Null
$db = Join-Path $root 'state.sqlite3'
$env:PYTHONPATH = Join-Path (Split-Path $PSScriptRoot -Parent) 'src'
& $exe @prefix -m rai_fabric --db $db init
& $exe @prefix -m rai_fabric --db $db submit --objective 'Проверка очереди и жизненного цикла чекпойнтов' --provider mock --workspace $root
& $exe @prefix -m rai_fabric --db $db run-once --provider mock
& $exe @prefix -m rai_fabric --db $db tasks
if ($LASTEXITCODE -ne 0) { throw "Демонстрация завершилась с ошибкой Python: $LASTEXITCODE" }
Write-Host "Демонстрационные данные: $root"
