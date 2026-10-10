#requires -Version 7.0
# Rassvet AI Fabric. Windows-only: процессы + Git через winget + журналы этапов.
# Установка Git предусмотрена пользовательским запросом; модели/авторизация не запускаются.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = 'C:\GIT\Rassvet_AI_Fabric'
$downloads = 'D:\ЗАГРУЗКИ'
$bundleName = 'RAiF-Windows-Discovery-09_7D.zip'
$expectedBundleSha256 = '85c6000764f1693711c6fe57a952a2c5aebf472a7b573a45d9a827865d908d35'
$bundlePath = Join-Path $downloads $bundleName
$runId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$runRoot = Join-Path $projectRoot ('.rai-fabric\windows-validation\runs\provider_v5_' + $runId)
$payloadRoot = Join-Path $runRoot 'payload'
$reportsRoot = Join-Path $runRoot 'reports'
$eventsPath = Join-Path $reportsRoot 'STAGES.jsonl'
$transcriptPath = Join-Path $reportsRoot 'TRANSCRIPT.log'
$resultPath = Join-Path $projectRoot ('RAiF-Windows-RESULT-DISCOVERY-' + $runId + '.zip')
$utf8 = [System.Text.UTF8Encoding]::new($false)
$stages = [System.Collections.Generic.List[object]]::new()
$errors = [System.Collections.Generic.List[string]]::new()
$transcriptStarted = $false
$bundleVerified = $false
$filesVerified = 0
$scannerVerdict = 'NOT_RUN'
$gitVerdict = 'NOT_CHECKED'
$gitVersion = ''
$exitCode = 2

function Assert-NotReparse {
    param([string] $Path)
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if (([int]$item.Attributes -band [int][IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Запрещён junction/symlink в пути рабочего каталога.'
        }
    }
}
function Append-Stage {
    param([string] $Name, [string] $Status, [string] $Details = '')
    $entry = [ordered]@{
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
        name = $Name
        status = $Status
        details = $Details
    }
    $script:stages.Add($entry)
    $jsonLine = $entry | ConvertTo-Json -Depth 5 -Compress
    [IO.File]::AppendAllText($script:eventsPath, $jsonLine + "`n", $script:utf8)
    Write-Host ('[{0}] {1}: {2}' -f $Status, $Name, $Details)
}
function Safe-Error {
    param([System.Exception] $Problem)
    # Сохраняем суть диагностики, удаляя возможные токены и имена пользователей.
    $message = [string]$Problem.Message
    $message = [regex]::Replace($message, '(?i)(access_token|refresh_token|id_token|authorization|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+', '$1=<СКРЫТО>')
    $message = [regex]::Replace($message, '(?i)\b[A-Z]:\\Users\\[^\\\s"/]+', '%WINDOWS_USER_HOME%')
    if ($message.Length -gt 280) { $message = $message.Substring(0,280) }
    return ($Problem.GetType().Name + ': ' + $message)
}
function Assert-Safe-Zip {
    param([string] $Path)
    Add-Type -AssemblyName System.IO.Compression.ZipFile
    $archive = [IO.Compression.ZipFile]::OpenRead($Path)
    try {
        foreach ($entry in $archive.Entries) {
            $p = $entry.FullName.Replace('\', '/')
            $components = @($p.Split('/') | Where-Object { $_ -ne '' })
            $badParts = @($components | Where-Object { $_ -eq '..' -or $_ -eq '.' })
            if ([string]::IsNullOrWhiteSpace($p) -or $p.StartsWith('/') -or $p.Contains(':') -or
                $badParts.Count -gt 0) {
                throw 'Небезопасный путь внутри ZIP.'
            }
        }
    } finally { $archive.Dispose() }
}
function Find-GitExecutable {
    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($cmd in @(Get-Command git.exe -All -ErrorAction SilentlyContinue)) {
        if ($cmd.PSObject.Properties['Source'] -and -not [string]::IsNullOrWhiteSpace([string]$cmd.Source)) {
            $candidates.Add([string]$cmd.Source)
        }
    }
    foreach ($candidate in @(
        (Join-Path $env:ProgramFiles 'Git\cmd\git.exe'),
        (Join-Path $env:ProgramFiles 'Git\bin\git.exe'),
        $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe' } else { '' }),
        $(if ([Environment]::GetEnvironmentVariable('ProgramFiles(x86)','Process')) {
            Join-Path ([Environment]::GetEnvironmentVariable('ProgramFiles(x86)','Process')) 'Git\cmd\git.exe'
        } else { '' })
    )) { if ($candidate) { $candidates.Add([string]$candidate) } }
    foreach ($path in $candidates) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        try {
            $version = @(& $path --version 2>$null)
            if ($LASTEXITCODE -eq 0 -and $version.Count -gt 0 -and [string]$version[0] -match 'git version') {
                return [ordered]@{ path = $path; version = ([string]$version[0]).Trim() }
            }
        } catch { }
    }
    return $null
}
function Install-GitViaWinget {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $winget) {
        Append-Stage 'Git / winget' 'BLOCKED' 'winget.exe не найден'
        return $false
    }
    Append-Stage 'Git / winget' 'START' 'Установка только Git.Git с --scope user, без повышения прав и без --force'
    $outFile = Join-Path $script:reportsRoot 'WINGET.stdout.log'
    $errFile = Join-Path $script:reportsRoot 'WINGET.stderr.log'
    $wingetArgs = @(
        'install', '--id', 'Git.Git', '--exact', '--source', 'winget',
        '--scope', 'user', '--silent', '--disable-interactivity',
        '--accept-source-agreements', '--accept-package-agreements'
    )
    try {
        $process = Start-Process -FilePath ([string]$winget.Source) -ArgumentList $wingetArgs `
            -NoNewWindow -RedirectStandardOutput $outFile -RedirectStandardError $errFile -PassThru -ErrorAction Stop
        if (-not $process.WaitForExit(180000)) {
            try { $process.Kill($true) } catch { }
            Append-Stage 'Git / winget' 'BLOCKED' 'Превышен лимит выполнения 180 секунд'
            return $false
        }
        if ($process.ExitCode -ne 0) {
            Append-Stage 'Git / winget' 'PARTIAL' ('Код установки: ' + $process.ExitCode)
            return $false
        }
        Append-Stage 'Git / winget' 'PASS' 'Команда установки успешно завершена'
        return $true
    } catch {
        Append-Stage 'Git / winget' 'PARTIAL' ('Ошибка процесса: ' + (Safe-Error $_.Exception))
        return $false
    }
}
function Save-Checkpoint {
    param([string]$Verdict)
    $record = [ordered]@{
        schema = 'RAI_FABRIC_WINDOWS_PROVIDER_RESULT/2'
        date_utc = [DateTime]::UtcNow.ToString('o')
        verdict = $Verdict
        package_sha256 = $script:expectedBundleSha256
        package_checked = $script:bundleVerified
        checked_payload_files = $script:filesVerified
        stage_count = $script:stages.Count
        stages = @($script:stages.ToArray())
        error_types = @($script:errors.ToArray())
        git = [ordered]@{ status = $script:gitVerdict; version = $script:gitVersion; method = 'Git.Git через winget при отсутствии' }
        scanner = $script:scannerVerdict
        result_zip = $script:resultPath
        restrictions = [ordered]@{
            models_invoked = $false
            oauth_performed = $false
            auth_files_read = $false
            process_commandlines_examined_only_in_memory = $true
            raw_process_commandlines_exported = $false
            bpr40_changed = $false
            control_tower_changed = $false
            linux_used = $false
        }
        next_cursor = 'RAI-FABRIC/09.7-E-PROCESS_DISCOVERY_RESULT_REVIEW'
    }
    [IO.File]::WriteAllText((Join-Path $script:reportsRoot 'CHECKPOINT.json'), (($record | ConvertTo-Json -Depth 15) + "`n"), $script:utf8)
}

if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'Нужен Windows PowerShell 7 (pwsh.exe).'
}
if (-not (Test-Path -LiteralPath $projectRoot -PathType Container)) {
    throw 'Каталог C:\GIT\Rassvet_AI_Fabric отсутствует; существующий проект не создаём автоматически.'
}
foreach ($path in @('C:\GIT', $projectRoot,
                    (Join-Path $projectRoot '.rai-fabric'),
                    (Join-Path $projectRoot '.rai-fabric\windows-validation'),
                    (Join-Path $projectRoot '.rai-fabric\windows-validation\runs'),
                    $runRoot)) { Assert-NotReparse $path }
[IO.Directory]::CreateDirectory($reportsRoot) | Out-Null
try {
    Start-Transcript -LiteralPath $transcriptPath -ErrorAction Stop | Out-Null
    $transcriptStarted = $true
} catch {
    Append-Stage 'Транскрипт' 'PARTIAL' 'Start-Transcript недоступен, журнал этапов сохранён отдельно'
}

try {
    Append-Stage 'PowerShell 7' 'PASS' $PSVersionTable.PSVersion.ToString()
    Append-Stage 'Проверка ZIP' 'START' $bundleName
    if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) {
        throw 'ZIP с диагностикой не найден в D:\ЗАГРУЗКИ.'
    }
    $actualSha256 = (Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $expectedBundleSha256) { throw 'SHA-256 исходного ZIP не совпадает.' }
    $bundleVerified = $true
    Append-Stage 'Проверка ZIP' 'PASS' $actualSha256
    Assert-Safe-Zip $bundlePath
    [IO.Directory]::CreateDirectory($payloadRoot) | Out-Null
    Expand-Archive -LiteralPath $bundlePath -DestinationPath $payloadRoot -ErrorAction Stop
    $manifestPath = Join-Path $payloadRoot 'manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($manifest.schema -ne 'RAI_FABRIC_DISCOVERY_PACKAGE/2') { throw 'Неизвестная схема манифеста ZIP.' }
    foreach ($file in @($manifest.files)) {
        $relative = ([string]$file.path).Replace('\','/')
        $components = @($relative.Split('/') | Where-Object { $_ -ne '' })
        $badParts = @($components | Where-Object { $_ -eq '..' -or $_ -eq '.' })
        if ([string]::IsNullOrEmpty($relative) -or $relative.StartsWith('/') -or $relative.Contains(':') -or
            $badParts.Count -gt 0) {
            throw 'Небезопасный путь в манифесте ZIP.'
        }
        $path = Join-Path $payloadRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Отсутствует файл из манифеста.' }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$file.sha256) {
            throw 'Контрольная сумма файла манифеста не совпала.'
        }
        $filesVerified++
    }
    Append-Stage 'Проверка файлов ZIP' 'PASS' ('Файлов: ' + $filesVerified)

    # Сначала процессы — даже если winget окажется недоступен.
    $scanner = Join-Path $payloadRoot 'tools\Inspect-RAiFProviders-v5.ps1'
    $scannerOutput = Join-Path $reportsRoot 'PROVIDERS.json'
    $scannerEvents = Join-Path $reportsRoot 'SCANNER_STAGES.jsonl'
    $scannerStdout = Join-Path $reportsRoot 'SCANNER.stdout.log'
    $scannerStderr = Join-Path $reportsRoot 'SCANNER.stderr.log'
    Append-Stage 'Процессы Codex/Antigravity' 'START' 'Поиск в Win32_Process.CommandLine; аргументы не архивируются'
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $scanner -OutputPath $scannerOutput -EventsPath $scannerEvents `
        1> $scannerStdout 2> $scannerStderr
    $scanExit = $LASTEXITCODE
    if ($scanExit -eq 0) {
        $scan = Get-Content -LiteralPath $scannerOutput -Raw -Encoding utf8 | ConvertFrom-Json
        if ($scan.schema -ne 'RAI_FABRIC_PROVIDER_DISCOVERY/2') { throw 'Неизвестная схема диагностического отчёта.' }
        $scannerVerdict = 'PASS'
        Append-Stage 'Процессы Codex/Antigravity' 'PASS' ('Codex: {0}; Antigravity: {1}' -f $scan.process_search.matching_counts.codex, $scan.process_search.matching_counts.antigravity)
    } else {
        $scannerVerdict = 'PARTIAL'
        Append-Stage 'Процессы Codex/Antigravity' 'PARTIAL' ('Сканер вернул ' + $scanExit + '; журналы сохранены')
    }

    Append-Stage 'Git' 'START' 'Проверка установленного Git'
    $git = Find-GitExecutable
    if ($null -eq $git) {
        $installOk = Install-GitViaWinget
        $git = Find-GitExecutable
        if ($null -eq $git) {
            $gitVerdict = 'PARTIAL'
            Append-Stage 'Git' 'PARTIAL' 'Git не найден после winget; установка/ручная проверка требуется'
        }
    }
    if ($null -ne $git) {
        $gitVerdict = 'PASS'
        $gitVersion = [string]$git.version
        Append-Stage 'Git' 'PASS' $gitVersion
    }
    if ($scannerVerdict -eq 'PASS' -and $gitVerdict -eq 'PASS') { $exitCode = 0 }
} catch {
    $errors.Add((Safe-Error $_.Exception))
    Append-Stage 'Непредвиденная ошибка' 'BLOCKED' ((Safe-Error $_.Exception) + '; см. лог и чекпойнт')
} finally {
    $verdict = if ($exitCode -eq 0) { 'PASS' } else { 'PARTIAL' }
    try { Append-Stage 'Завершение' $verdict 'Формирование результирующего ZIP в корне проекта' } catch { }
    if ($transcriptStarted) { try { Stop-Transcript -ErrorAction Stop | Out-Null } catch { } }
    try {
        Save-Checkpoint $verdict
        if (Test-Path -LiteralPath $resultPath) { throw 'Результирующий ZIP уже существует, перезапись запрещена.' }
        Compress-Archive -Path (Join-Path $reportsRoot '*') -DestinationPath $resultPath -CompressionLevel Optimal -ErrorAction Stop
        $hash = (Get-FileHash -LiteralPath $resultPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Host ('РЕЗУЛЬТАТ: ' + $resultPath)
        Write-Host ('SHA256: ' + $hash)
        Write-Host ('ВЕРДИКТ: ' + $verdict)
    } catch {
        Write-Error 'Не удалось создать результирующий ZIP; журналы остаются в каталоге runs.' -ErrorAction Continue
        $exitCode = 3
    }
}
exit $exitCode
