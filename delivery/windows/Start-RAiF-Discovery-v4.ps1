# Rassvet AI Fabric — запуск read-only диагностики локальных провайдеров.
# Windows PowerShell 5.1; входные файлы: D:\ЗАГРУЗКИ; результат: корень C:\GIT\Rassvet_AI_Fabric.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$packagePath = 'D:\ЗАГРУЗКИ\RAiF-Windows-Discovery-09_7B.zip'
$expectedSha256 = '627cd427f48a64b24bb4677a3b905e90fb581c9396a5737144d8349078f676ed'
$projectRoot = 'C:\GIT\Rassvet_AI_Fabric'
$runId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8)
$validationRoot = Join-Path $projectRoot '.rai-fabric\windows-validation'
$runRoot = Join-Path $validationRoot (Join-Path 'runs' ('discovery_' + $runId))
$extractedRoot = Join-Path $runRoot 'payload'
$reportsRoot = Join-Path $runRoot 'reports'
$resultZip = Join-Path $projectRoot ('RAiF-Windows-RESULT-DISCOVERY-' + $runId + '.zip')
$steps = @()
$errorsList = @()
$verdict = 'BLOCKED'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Append-Step {
    param([string]$Name,[string]$Status,[string]$Note)
    $script:steps += [ordered]@{ name=$Name; status=$Status; note=$Note }
}
function Protect-Against-Reparse {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        $entry = Get-Item -LiteralPath $Path -Force
        if (([int]$entry.Attributes -band [int][IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw ('Путь содержит junction/symlink: ' + $Path)
        }
    }
}
function Write-JsonFile {
    param([string]$Path, $Value)
    $text = $Value | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($Path, $text + [Environment]::NewLine, $utf8)
}

if (-not (Test-Path -LiteralPath $projectRoot -PathType Container)) {
    throw ('Корень проекта не существует: ' + $projectRoot)
}
if ($env:OS -ne 'Windows_NT') { throw 'Этот запускатор предназначен только для Windows.' }
foreach ($path in @('C:\GIT',$projectRoot,(Join-Path $projectRoot '.rai-fabric'),$validationRoot,(Join-Path $validationRoot 'runs'))) {
    Protect-Against-Reparse $path
}
New-Item -ItemType Directory -Path $reportsRoot -Force -ErrorAction Stop | Out-Null

try {
    if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) {
        throw 'Пакет диагностики не найден рядом с PS1 в D:\ЗАГРУЗКИ.'
    }
    $actualSha256 = (Get-FileHash -LiteralPath $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        Append-Step 'Проверка ZIP' 'BLOCKED' 'SHA-256 не совпадает'
        throw 'Проверка SHA-256 пакета не пройдена.'
    }
    Append-Step 'Проверка ZIP' 'PASS' $actualSha256

    New-Item -ItemType Directory -Path $extractedRoot -Force -ErrorAction Stop | Out-Null
    Expand-Archive -LiteralPath $packagePath -DestinationPath $extractedRoot -ErrorAction Stop
    $manifestPath = Join-Path $extractedRoot 'manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 'RAI_FABRIC_DISCOVERY_PACKAGE/1') { throw 'Схема манифеста не распознана.' }
    $checks = 0
    foreach ($file in $manifest.files) {
        $relative = [string]$file.path
        if ($relative.StartsWith('/') -or $relative.StartsWith('\\') -or
            ($relative -split '[/\\]' | Where-Object { $_ -eq '..' }).Count -gt 0 -or
            $relative.Contains(':')) {
            throw 'Манифест содержит небезопасный путь.'
        }
        $full = Join-Path $extractedRoot ($relative -replace '/', '\')
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw 'Отсутствует файл из манифеста.' }
        $sha = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($sha -ne [string]$file.sha256) { throw 'SHA-256 распакованного файла не совпадает.' }
        $checks += 1
    }
    Append-Step 'Проверка содержимого' 'PASS' ('Проверено файлов: ' + $checks)

    $probePath = Join-Path $extractedRoot 'tools\Inspect-RAiFProviders.ps1'
    $providersPath = Join-Path $reportsRoot 'providers.json'
    $stdoutPath = Join-Path $reportsRoot 'scanner.stdout.txt'
    $stderrPath = Join-Path $reportsRoot 'scanner.stderr.txt'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $probePath -OutputPath $providersPath 1> $stdoutPath 2> $stderrPath
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw ('Сканер метаданных завершился с кодом ' + $code) }
    if (-not (Test-Path -LiteralPath $providersPath -PathType Leaf)) { throw 'Файл providers.json не создан.' }
    $providers = Get-Content -LiteralPath $providersPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($providers.schema -ne 'RAI_FABRIC_PROVIDER_DISCOVERY/1') { throw 'Недопустимый результат сканера.' }
    Append-Step 'Сбор метаданных' 'PASS' 'Не запускались модели и авторизация'
    $verdict = 'PASS_READONLY_DISCOVERY'
} catch {
    $msg = [string]$_.Exception.Message
    if ($msg.Length -gt 300) { $msg = $msg.Substring(0,300) }
    $errorsList += $msg
    Append-Step 'Завершение' 'BLOCKED' 'См. журнал диагностики'
} finally {
    $checkpoint = [ordered]@{
        schema='RAI_FABRIC_WINDOWS_DISCOVERY_RESULT/1'
        timestamp_utc=[DateTime]::UtcNow.ToString('o')
        verdict=$verdict
        machine_os='Windows'
        project_root=$projectRoot
        package_sha256=$expectedSha256
        result_zip=$resultZip
        steps=$steps
        errors=$errorsList
        restrictions=[ordered]@{
            auth_profiles_read=$false
            auth_tokens_read=$false
            oauth_login_performed=$false
            codex_launched=$false
            antigravity_launched=$false
            model_inference_calls=0
            paid_api_calls=0
            bpr40_changed=$false
            control_tower_changed=$false
        }
        next_cursor='RAI-FABRIC/09.7-C-PROVIDER_GATE_AND_OAUTH_CONSENT'
    }
    Write-JsonFile (Join-Path $reportsRoot 'CHECKPOINT.json') $checkpoint
    try {
        if (Test-Path -LiteralPath $resultZip) { throw 'Результирующий ZIP уже существует; перезапись запрещена.' }
        Compress-Archive -Path (Join-Path $reportsRoot '*') -DestinationPath $resultZip -CompressionLevel Optimal -ErrorAction Stop
        $resultHash = (Get-FileHash -LiteralPath $resultZip -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Host ('Результат: ' + $resultZip)
        Write-Host ('SHA256 результата: ' + $resultHash)
        Write-Host ('Статус: ' + $verdict)
    } catch {
        Write-Error ('Не удалось упаковать результат: ' + $_.Exception.Message) -ErrorAction Continue
        throw
    }
}
if ($verdict -ne 'PASS_READONLY_DISCOVERY') { exit 2 }
exit 0
