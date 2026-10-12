# Испытание SQLite-очереди и подставного Codex по stdio; никакого настоящего Codex или OAuth.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-python.ps1')
$workspace = Join-Path $env:TEMP ('rai-codex-mock-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $workspace | Out-Null
$db = Join-Path $workspace 'state.sqlite3'
$previous = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
try {
    $env:PYTHONPATH = Join-Path (Split-Path $PSScriptRoot -Parent) 'src'
    $selection = Resolve-RAiFPython
    $exe = [string]$selection.FilePath
    $prefix = @($selection.Prefix)
    & $exe @prefix -m rai_fabric --db $db init
    if ($LASTEXITCODE -ne 0) { throw "Ошибка инициализации: $LASTEXITCODE" }
    & $exe @prefix -m rai_fabric --db $db submit --provider codex-mock --objective 'Проверка подставного Codex без обращений к модели' --workspace $workspace --task-id codex-mock-smoke
    if ($LASTEXITCODE -ne 0) { throw "Ошибка создания задачи: $LASTEXITCODE" }
    & $exe @prefix -m rai_fabric --db $db run-once --provider codex-mock --timeout 15
    if ($LASTEXITCODE -ne 0) { throw "Ошибка mock-исполнителя: $LASTEXITCODE" }
    & $exe @prefix -m rai_fabric --db $db task codex-mock-smoke
    if ($LASTEXITCODE -ne 0) { throw "Ошибка чтения чекпойнта: $LASTEXITCODE" }
    Write-Host "Тестовая БД (без подписных вызовов): $db"
} finally {
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $previous, 'Process')
}
