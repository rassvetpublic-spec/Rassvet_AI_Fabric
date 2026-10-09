# Запуск тестов выбранным Python в отдельном процессе без изменения глобальных настроек.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$oldPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
try {
    $env:PYTHONPATH = Join-Path $root 'src'
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m unittest discover -s (Join-Path $root 'tests') -v
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m unittest discover -s (Join-Path $root 'tests') -v
    } else {
        throw 'Python не найден: для проекта необходим Python 3.11 или новее.'
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Ошибка тестирования: Python вернул код $LASTEXITCODE"
    }
    Write-Host 'Автоматические тесты успешно завершены.'
} finally {
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $oldPythonPath, 'Process')
}
