# Локальный smoke test. Новая временная БД, имитатор вместо модели. Учётные данные не используются.
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:TEMP ('rai-fabric-demo-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $root | Out-Null
$db = Join-Path $root 'state.sqlite3'
$oldPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
try {
    $env:PYTHONPATH = Join-Path (Split-Path $PSScriptRoot -Parent) 'src'
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $exe = 'python'
        $prefix = @()
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $exe = 'py'
        $prefix = @('-3')
    } else {
        throw 'Python не найден: демонстрация невозможна.'
    }
    & $exe @prefix -m rai_fabric --db $db init
    if ($LASTEXITCODE -ne 0) { throw "Сбой инициализации: $LASTEXITCODE" }
    & $exe @prefix -m rai_fabric --db $db submit --objective 'Проверка очереди и жизненного цикла чекпойнтов' --provider mock --workspace $root
    if ($LASTEXITCODE -ne 0) { throw "Сбой создания задачи: $LASTEXITCODE" }
    & $exe @prefix -m rai_fabric --db $db run-once --provider mock
    if ($LASTEXITCODE -ne 0) { throw "Сбой исполнения имитатора: $LASTEXITCODE" }
    & $exe @prefix -m rai_fabric --db $db tasks
    if ($LASTEXITCODE -ne 0) { throw "Сбой чтения задач: $LASTEXITCODE" }
    Write-Host "Демонстрационные данные: $root"
} finally {
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $oldPythonPath, 'Process')
}
