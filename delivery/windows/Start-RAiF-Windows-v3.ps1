#requires -Version 5.1
<#
Rassvet AI Fabric — однофайловый запуск безопасной Windows-диагностики (v3).
Вход: ZIP из D:\ЗАГРУЗКИ, зафиксированный по SHA-256.
Выход: C:\GIT\Rassvet_AI_Fabric\RAiF-Windows-RESULT-*.zip
Никаких входов в ChatGPT / Antigravity, запросов моделей и изменений CODEX_HOME/BPR40.
Обход ExecutionPolicy допускается только параметром -ExecutionPolicy Bypass у запускающего powershell.exe.
#>
[CmdletBinding()]
param(
    [string]$ZipPath = 'D:\ЗАГРУЗКИ\RAiF-Windows-Source-0a41a338.zip',
    [string]$RuntimeRoot = 'C:\GIT\Rassvet_AI_Fabric',
    [switch]$NoDependencyDownload
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$ExpectedCommit = '0a41a338fe9c866206fe206381e213eb5460b456'
$ExpectedTree = '3d33f72a797e1c8aabf1365972206ff1f5986751'
$ExpectedZipSha256 = '3a63ebabf51ad112ef5798dcc958fbdb5bf902ba7d06da0eaa833ef63913f16f'
$ExpectedFiles = 95
$Utf8 = [System.Text.UTF8Encoding]::new($false)
$StartTime = [DateTime]::UtcNow
$RunId = (Get-Date).ToString('yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8)
$WorkBase = Join-Path $RuntimeRoot '.rai-fabric\windows-validation'
$RunsParent = Join-Path $WorkBase 'runs'
$RunDir = Join-Path $RunsParent $RunId
$ReportDir = Join-Path $RunDir 'reports'
$ResultsDir = $RuntimeRoot
$ResultZip = Join-Path $ResultsDir ('RAiF-Windows-RESULT-' + $RunId + '.zip')
$UnpackedDir = Join-Path $RunDir 'payload'
$SourceDir = Join-Path $UnpackedDir 'Rassvet_AI_Fabric'
$VirtualEnv = Join-Path $RunDir 'venv'
$IsolatedTemp = Join-Path $RunDir 'temp'
$IsolatedLocalAppData = Join-Path $RunDir 'LocalAppData'
$IsolatedRoamingAppData = Join-Path $RunDir 'RoamingAppData'
$PythonInVenv = Join-Path $VirtualEnv 'Scripts\python.exe'
$Records = New-Object 'System.Collections.Generic.List[object]'
$Issues = New-Object 'System.Collections.Generic.List[string]'
$Verdict = 'BLOCKED'
$Initialized = $false

function Assert-OrdinaryDirectory([string]$PathToCheck) {
    if (Test-Path -LiteralPath $PathToCheck) {
        $item = Get-Item -LiteralPath $PathToCheck -Force
        if (-not $item.PSIsContainer) { throw "Ожидался каталог: $PathToCheck" }
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Отказ: каталог является junction/symlink: $PathToCheck"
        }
    }
}

function Quote-WindowsArgument([string]$Value) {
    if ($null -eq $Value) { return '""' }
    if ($Value -match '[\r\n]') { throw 'Переводы строк в аргументах запрещены.' }
    # Все значения задаёт сам проверенный запускатор; внешних командных строк нет.
    return '"' + $Value.Replace('"','\"') + '"'
}

function Invoke-RecordedProcess {
    param(
        [string]$Name,
        [string]$Executable,
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 180,
        [string]$WorkingDirectory = $SourceDir,
        [switch]$UseVenv
    )
    $outPath = Join-Path $ReportDir ($Name + '.stdout.txt')
    $errPath = Join-Path $ReportDir ($Name + '.stderr.txt')
    $startedAt = [DateTime]::UtcNow
    $stepStatus = 'FAILED'
    $exitCode = $null
    $explanation = $null
    $process = $null
    try {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $Executable
        $info.Arguments = (($Arguments | ForEach-Object { Quote-WindowsArgument ([string]$_) }) -join ' ')
        $info.WorkingDirectory = $WorkingDirectory
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $info.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $info.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        $info.EnvironmentVariables['PYTHONUTF8'] = '1'
        $info.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
        $info.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'
        $info.EnvironmentVariables['PYTHONPATH'] = Join-Path $SourceDir 'src'
        $info.EnvironmentVariables['PIP_NO_INPUT'] = '1'
        $info.EnvironmentVariables['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
        $info.EnvironmentVariables['PIP_CACHE_DIR'] = Join-Path $RunDir 'pip-cache'
        $info.EnvironmentVariables['TEMP'] = $IsolatedTemp
        $info.EnvironmentVariables['TMP'] = $IsolatedTemp
        $info.EnvironmentVariables['LOCALAPPDATA'] = $IsolatedLocalAppData
        $info.EnvironmentVariables['APPDATA'] = $IsolatedRoamingAppData
        if ($UseVenv) {
            $info.EnvironmentVariables['PATH'] = (Join-Path $VirtualEnv 'Scripts') + ';' + $info.EnvironmentVariables['PATH']
        }
        # Секреты удаляются только из окружения дочернего тестового процесса.
        foreach ($key in @($info.EnvironmentVariables.Keys)) {
            if ([string]$key -match '^(OPENAI_|CHATGPT_|CODEX_|ANTIGRAVITY_|GEMINI_|GOOGLE_APPLICATION_CREDENTIALS$|GITHUB_TOKEN$|GH_TOKEN$|AZURE_.*TOKEN|AWS_.*KEY|.*_API_KEY$|.*_AUTH_TOKEN$|PIP_INDEX_URL$|PIP_EXTRA_INDEX_URL$)') {
                [void]$info.EnvironmentVariables.Remove([string]$key)
            }
        }
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $info
        if (-not $process.Start()) { throw 'Процесс не стартовал.' }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $completed = $process.WaitForExit($TimeoutSeconds * 1000)
        if (-not $completed) {
            try { $process.Kill() } catch {}
            [void]$process.WaitForExit(10000)
            $stepStatus = 'TIMEOUT'
            $explanation = "Тайм-аут ${TimeoutSeconds}с; дерево дочерних процессов отдельно не проверялось."
        } else {
            $exitCode = [int]$process.ExitCode
            $stepStatus = if ($exitCode -eq 0) { 'PASS' } else { 'FAILED' }
        }
        if ($stdoutTask.Wait(15000)) {
            [IO.File]::WriteAllText($outPath, [string]$stdoutTask.Result, $Utf8)
        } else {
            [IO.File]::WriteAllText($outPath, 'Не удалось завершить чтение stdout.', $Utf8)
        }
        if ($stderrTask.Wait(15000)) {
            [IO.File]::WriteAllText($errPath, [string]$stderrTask.Result, $Utf8)
        } else {
            [IO.File]::WriteAllText($errPath, 'Не удалось завершить чтение stderr.', $Utf8)
        }
    } catch {
        $explanation = $_.Exception.Message
        if (-not (Test-Path -LiteralPath $errPath)) {
            [IO.File]::WriteAllText($errPath, $explanation, $Utf8)
        }
    } finally {
        if ($null -ne $process) { $process.Dispose() }
    }
    $record = [ordered]@{
        name = $Name
        status = $stepStatus
        exit_code = $exitCode
        started_utc = $startedAt.ToString('o')
        duration_seconds = [math]::Round(([DateTime]::UtcNow - $startedAt).TotalSeconds, 2)
        note = $explanation
    }
    Write-Host ('[' + $stepStatus + '] ' + $Name)
    return [pscustomobject]$record
}

function Confirm-ZipAndManifest {
    $foundHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($foundHash -ne $ExpectedZipSha256) {
        throw "SHA-256 ZIP не совпадает: ожидался $ExpectedZipSha256, получен $foundHash"
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $entries = @($archive.Entries | Where-Object { -not [string]::IsNullOrEmpty($_.Name) })
        if ($entries.Count -ne $ExpectedFiles) { throw "ZIP содержит $($entries.Count) файлов вместо $ExpectedFiles." }
        $names = @{}
        foreach ($entry in $archive.Entries) {
            $name = [string]$entry.FullName
            if ($name -notmatch '^Rassvet_AI_Fabric/' -or $name.Contains('\') -or $name.Contains(':') -or $name.Contains('//') -or $name -match '(^|/)\.\.(/|$)') {
                throw "Недопустимый путь в ZIP: $name"
            }
            if (-not [string]::IsNullOrEmpty($entry.Name)) {
                if ($names.ContainsKey($name)) { throw "Повторяющееся имя в ZIP: $name" }
                $names[$name] = $true
            }
        }
    } finally {
        $archive.Dispose()
    }
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $UnpackedDir -Force
    $manifestPath = Join-Path $SourceDir 'SHA256SUMS.txt'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Нет SHA256SUMS.txt' }
    $lines = @(Get-Content -LiteralPath $manifestPath -Encoding UTF8 | Where-Object { $_.Length -gt 0 })
    if ($lines.Count -ne ($ExpectedFiles - 1)) { throw 'Некорректное количество записей SHA256SUMS.txt.' }
    $allFiles = @(Get-ChildItem -LiteralPath $SourceDir -File -Recurse -Force)
    if ($allFiles.Count -ne $ExpectedFiles) { throw 'Обнаружены неожиданные файлы после распаковки.' }
    foreach ($file in $allFiles) {
        if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Обнаружена символическая ссылка в пакете.'
        }
    }
    $validated = 0
    foreach ($line in $lines) {
        if ($line -notmatch '^([a-f0-9]{64})  (.+)$') { throw "Неверная строка манифеста: $line" }
        $expected = $Matches[1]
        $relative = $Matches[2]
        if ($relative.StartsWith('/') -or $relative.Contains('\') -or $relative.Contains(':') -or $relative -match '(^|/)\.\.(/|$)') {
            throw "Небезопасный путь манифеста: $relative"
        }
        $absolute = Join-Path $SourceDir ($relative.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $absolute -PathType Leaf)) { throw "Не найден файл: $relative" }
        $actual = (Get-FileHash -LiteralPath $absolute -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw "Ошибка контрольной суммы: $relative" }
        $validated++
    }
    [IO.File]::WriteAllText((Join-Path $ReportDir 'package_verified.txt'),
        "Git commit: $ExpectedCommit`nGit tree: $ExpectedTree`nZIP SHA256: $ExpectedZipSha256`nПроверено файлов: $ExpectedFiles`nЗаписей SHA256: $validated`n", $Utf8)
}

function New-CompatibleExecutionCopy {
    # SHA-256 и список файлов проверены в неизменённой копии payload.
    # Запускаемые PS1 копируются отдельно с UTF-8 BOM для Windows PowerShell 5.1.
    $workingRoot = Join-Path $RunDir 'execution'
    [void](New-Item -ItemType Directory -Path $workingRoot -Force)
    $workingSource = Join-Path $workingRoot 'Rassvet_AI_Fabric'
    Copy-Item -LiteralPath $SourceDir -Destination $workingSource -Recurse -Force
    if (-not (Test-Path -LiteralPath $workingSource -PathType Container)) {
        throw 'Не создана отдельная рабочая копия исходников.'
    }
    $bom = [System.Text.UTF8Encoding]::new($true)
    $converted = 0
    foreach ($file in @(Get-ChildItem -LiteralPath (Join-Path $workingSource 'scripts') -Filter '*.ps1' -File -Recurse)) {
        $text = [IO.File]::ReadAllText($file.FullName, [Text.Encoding]::UTF8)
        [IO.File]::WriteAllText($file.FullName, $text, $bom)
        $converted++
    }
    [IO.File]::WriteAllText((Join-Path $ReportDir 'execution_copy.txt'),
        "Оригинал payload не изменён после SHA-256 проверки.`nPS1 в отдельной копии получили UTF-8 BOM: $converted`n", $Utf8)
    return $workingSource
}

$ReportPackaged = $false
try {
    if ($env:OS -ne 'Windows_NT') { throw 'Требуется Windows. Linux и macOS не поддерживаются.' }
    foreach ($dir in @($RuntimeRoot, (Join-Path $RuntimeRoot '.rai-fabric'), $WorkBase, $RunsParent, $ResultsDir)) {
        Assert-OrdinaryDirectory $dir
    }
    [void](New-Item -ItemType Directory -Path $ReportDir -Force)
    [void](New-Item -ItemType Directory -Path $ResultsDir -Force)
    foreach ($folder in @($IsolatedTemp, $IsolatedLocalAppData, $IsolatedRoamingAppData)) {
        [void](New-Item -ItemType Directory -Path $folder -Force)
    }
    $Initialized = $true
    Write-Host "Распаковка и тесты: $RunDir"
    if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
        throw "Отсутствует пакет $ZipPath. Положите ZIP и PS1 в D:\ЗАГРУЗКИ."
    }
    Confirm-ZipAndManifest
    $Records.Add([pscustomobject]@{ name='Проверка ZIP и SHA256'; status='PASS'; exit_code=0; note=$ExpectedCommit })
    # Не меняем побайтно проверенный payload: совместимость PS5.1 готовим в отдельной копии.
    $SourceDir = New-CompatibleExecutionCopy

    # v3: WindowsApps python.exe иногда запускает псевдоним, печатающий только "Python ".
    # Некоторые py.exe являются shim к python.exe и НЕ принимают -3.
    # Каждый найденный исполняемый файл проверяем реальным запуском с -c.
    $psExe = Join-Path $PSHOME 'powershell.exe'
    $pythonExe = $null
    $pythonPrefix = @()
    $candidates = New-Object 'System.Collections.Generic.List[object]'
    $seen = @{}
    foreach ($commandName in @('python.exe', 'py.exe', 'python3.exe')) {
        foreach ($cmd in @(Get-Command -Name $commandName -All -ErrorAction SilentlyContinue)) {
            $exe = [string]$cmd.Source
            if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { continue }
            $key = $exe.ToLowerInvariant() + '|direct'
            if (-not $seen.ContainsKey($key)) {
                $seen[$key] = $true
                $candidates.Add([pscustomobject]@{exe=$exe;prefix=@()})
            }
            # Только настоящий py.exe получает дополнительную попытку -3.
            if ($commandName -eq 'py.exe' -and [IO.Path]::GetFileName($exe).Equals('py.exe', [StringComparison]::OrdinalIgnoreCase)) {
                $key = $exe.ToLowerInvariant() + '|launcher3'
                if (-not $seen.ContainsKey($key)) {
                    $seen[$key] = $true
                    $candidates.Add([pscustomobject]@{exe=$exe;prefix=@('-3')})
                }
            }
        }
    }
    # Поиск реального python.exe по стандартному пользовательскому каталогу,
    # даже если WindowsApps перехватывает имена python и py в PATH.
    $localAppData = [Environment]::GetFolderPath('LocalApplicationData')
    if (-not [string]::IsNullOrWhiteSpace($localAppData)) {
        $userPythonRoot = Join-Path $localAppData 'Programs\Python'
        if (Test-Path -LiteralPath $userPythonRoot -PathType Container) {
            foreach ($dir in @(Get-ChildItem -LiteralPath $userPythonRoot -Directory -ErrorAction SilentlyContinue | Sort-Object -Property Name -Descending)) {
                $exe = Join-Path $dir.FullName 'python.exe'
                $key = $exe.ToLowerInvariant() + '|direct'
                if ((Test-Path -LiteralPath $exe -PathType Leaf) -and -not $seen.ContainsKey($key)) {
                    $seen[$key] = $true
                    $candidates.Add([pscustomobject]@{exe=$exe;prefix=@()})
                }
            }
        }
    }
    $candidateNo = 0
    foreach ($candidate in $candidates) {
        $candidateNo++
        $probeArgs = @($candidate.prefix) + @('-c', 'import sys; print(sys.executable); print(sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3, 11) else 5)')
        $probe = Invoke-RecordedProcess -Name ('02-python-probe-' + $candidateNo) -Executable $candidate.exe -Arguments $probeArgs -TimeoutSeconds 25
        if ($probe.status -eq 'PASS') {
            $pythonExe = $candidate.exe
            $pythonPrefix = @($candidate.prefix)
            $Records.Add($probe)
            break
        }
        $probe.status = 'SKIPPED'
        $probe.note = 'Кандидат Python отклонён; переход к следующему.'
        $Records.Add($probe)
    }
    if ($null -eq $pythonExe) { throw 'Не найден работающий Python 3.11+. Проверьте 02-python-probe-*.stderr.txt.' }

    $venvCheck = Invoke-RecordedProcess -Name '03-venv' -Executable $pythonExe -Arguments (@($pythonPrefix) + @('-m','venv',$VirtualEnv)) -TimeoutSeconds 120
    $Records.Add($venvCheck)
    if ($venvCheck.status -ne 'PASS' -or -not (Test-Path -LiteralPath $PythonInVenv -PathType Leaf)) {
        throw 'Python не создал изолированное виртуальное окружение.'
    }
    $versionCheck = Invoke-RecordedProcess -Name '04-python-version' -Executable $PythonInVenv -Arguments @('-c','import sys; print(sys.version); sys.exit(0 if sys.version_info >= (3,11) else 2)') -TimeoutSeconds 30 -UseVenv
    $Records.Add($versionCheck)
    if ($versionCheck.status -ne 'PASS') { throw 'Невозможно запустить Python внутри venv.' }
    # Preflight только после venv: дочерний PowerShell видит исправный python.exe первым в PATH.
    $preflightCheck = Invoke-RecordedProcess -Name '05-preflight' -Executable $psExe -Arguments @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $SourceDir 'scripts\windows-preflight.ps1'),'-RequireWindows') -TimeoutSeconds 45 -UseVenv
    $Records.Add($preflightCheck)
    if ($NoDependencyDownload) {
        $Records.Add([pscustomobject]@{name='04-install-dependencies';status='SKIPPED';exit_code=$null;note='Отключено параметром -NoDependencyDownload'})
    } else {
        # Зависимости скачиваются только из официального PyPI, только в новый venv.
        $Records.Add((Invoke-RecordedProcess -Name '06-install-dependencies' -Executable $PythonInVenv -Arguments @('-m','pip','install','--disable-pip-version-check','--no-input','--index-url','https://pypi.org/simple','PyJWT[crypto]>=2.10,<3') -TimeoutSeconds 240 -UseVenv))
    }
    $Records.Add((Invoke-RecordedProcess -Name '07-unittests' -Executable $psExe -Arguments @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $SourceDir 'scripts\run-tests.ps1')) -TimeoutSeconds 240 -UseVenv))
    $Records.Add((Invoke-RecordedProcess -Name '08-demo-mock' -Executable $psExe -Arguments @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $SourceDir 'scripts\demo.ps1')) -TimeoutSeconds 90 -UseVenv))
    $Records.Add((Invoke-RecordedProcess -Name '09-demo-codex-mock' -Executable $psExe -Arguments @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $SourceDir 'scripts\demo-codex-mock.ps1')) -TimeoutSeconds 90 -UseVenv))
    $gpuCmd = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $gpuCmd) {
        $Records.Add((Invoke-RecordedProcess -Name '10-nvidia-readonly' -Executable $gpuCmd.Source -Arguments @('--query-gpu=name,memory.total,driver_version','--format=csv,noheader') -TimeoutSeconds 20))
    } else {
        $Records.Add([pscustomobject]@{ name='08-nvidia-readonly';status='SKIPPED';exit_code=$null;note='nvidia-smi не обнаружен в PATH' })
    }
    $failed = @($Records | Where-Object { $_.status -eq 'FAILED' -or $_.status -eq 'TIMEOUT' })
    $critical = @($Records | Where-Object { $_.name -in @('03-venv','04-python-version','05-preflight','06-install-dependencies','07-unittests','08-demo-mock','09-demo-codex-mock') -and $_.status -ne 'PASS' })
    $Verdict = if ($critical.Count -eq 0 -and $failed.Count -eq 0) { 'PASS' } else { 'PARTIAL' }
    if ($Verdict -ne 'PASS') { $Issues.Add('Один или несколько этапов не прошли, см. отдельные журналы.') }
} catch {
    $Verdict = 'BLOCKED'
    $Issues.Add($_.Exception.Message)
    Write-Warning ('Проверка остановлена: ' + $_.Exception.Message)
} finally {
    try {
        if (-not (Test-Path -LiteralPath $ReportDir)) { [void](New-Item -ItemType Directory -Path $ReportDir -Force) }
        if (-not (Test-Path -LiteralPath $ResultsDir)) { [void](New-Item -ItemType Directory -Path $ResultsDir -Force) }
        $summary = [ordered]@{
            schema = 'RAI_FABRIC_WINDOWS_HOST_RESULT/1'
            created_utc = $StartTime.ToString('o')
            completed_utc = [DateTime]::UtcNow.ToString('o')
            verdict = $Verdict
            source_commit = $ExpectedCommit
            source_tree = $ExpectedTree
            source_zip_sha256 = $ExpectedZipSha256
            result_zip_location = $ResultZip
            compatibility = 'PowerShell 5.1: utf8-bom; v3-поиск реального python.exe и preflight после venv; ZIP не изменён'
            language = 'ru-RU'
            system = [ordered]@{
                windows = ($env:OS -eq 'Windows_NT')
                powershell = $PSVersionTable.PSVersion.ToString()
                execution_policy_in_process = 'Bypass через внешний параметр; постоянные политики не менялись'
            }
            restrictions = [ordered]@{
                actual_codex_launched = $false
                actual_antigravity_launched = $false
                chatgpt_oauth_performed = $false
                model_inference_calls = 0
                external_api_billing = 'NOT_USED'
                scripts_limited_to_mock_tests = $true
                bpr40_mutated = $false
                code_home_mutated = $false
            }
            steps = @($Records.ToArray())
            errors = @($Issues.ToArray())
            cursor = 'RAI-FABRIC/09.7-HOST_V3_RESULT_REVIEW'
        }
        [IO.File]::WriteAllText((Join-Path $ReportDir 'CHECKPOINT.json'), ($summary | ConvertTo-Json -Depth 10), $Utf8)
        [IO.File]::WriteAllText((Join-Path $ReportDir 'ПРОЧИТАЙ_МЕНЯ.txt'),
            "Rassvet AI Fabric — диагностический архив Windows.`nВердикт: $Verdict`nОбязательный файл: CHECKPOINT.json`nСекреты, профили Codex и файлы BPR40 намеренно не включаются.`nПришлите весь получившийся ZIP в чат, даже если тесты не прошли.`n",$Utf8)
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        if (Test-Path -LiteralPath $ResultZip) { throw 'Повторное создание результата с тем же именем запрещено.' }
        [IO.Compression.ZipFile]::CreateFromDirectory($ReportDir,$ResultZip,[IO.Compression.CompressionLevel]::Optimal,$false)
        $ReportPackaged = $true
        $ResultHash = (Get-FileHash -LiteralPath $ResultZip -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Host ''
        Write-Host '===== Rassvet AI Fabric: результат ====='
        Write-Host "Вердикт: $Verdict"
        Write-Host "ZIP с результатами: $ResultZip"
        Write-Host "SHA256 результата: $ResultHash"
        Write-Host 'Передайте ZIP из корня C:\GIT\Rassvet_AI_Fabric обратно в этот чат.'
        Write-Host 'Курсор: RAI-FABRIC/09.7-HOST_V3_RESULT_REVIEW'
    } catch {
        Write-Error ('Не удалось создать диагностический ZIP: ' + $_.Exception.Message) -ErrorAction Continue
    }
}
if (-not $ReportPackaged) { exit 3 }
if ($Verdict -ne 'PASS') { exit 2 }
exit 0
