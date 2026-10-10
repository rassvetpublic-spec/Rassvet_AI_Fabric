#requires -Version 7.0
# Диагностика Rassvet AI Fabric: процессы и строки запуска (без публикации аргументов).
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $OutputPath,
    [Parameter(Mandatory = $true)] [string] $EventsPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
$events = [System.Collections.Generic.List[object]]::new()
$errors = [System.Collections.Generic.List[string]]::new()

function Write-Event {
    param([string] $Stage, [string] $Status, [string] $Details = '')
    $entry = [ordered]@{
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
        stage = $Stage
        status = $Status
        details = $Details
    }
    $script:events.Add($entry)
    Write-Host ('[{0}] {1}: {2}' -f $Status, $Stage, $Details)
}
function Clean-Path {
    param([AllowEmptyString()][string] $Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $prefixes = @(
        @{ Root = $env:USERPROFILE; Token = '%USERPROFILE%' },
        @{ Root = $env:LOCALAPPDATA; Token = '%LOCALAPPDATA%' },
        @{ Root = $env:APPDATA; Token = '%APPDATA%' },
        @{ Root = $env:ProgramFiles; Token = '%PROGRAMFILES%' },
        @{ Root = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)', 'Process'); Token = '%PROGRAMFILES(X86)%' }
    ) | Sort-Object { if ($_.Root) { $_.Root.Length } else { 0 } } -Descending
    foreach ($prefix in $prefixes) {
        if (-not [string]::IsNullOrWhiteSpace($prefix.Root) -and
            $Value.StartsWith([string]$prefix.Root, [StringComparison]::OrdinalIgnoreCase)) {
            return $prefix.Token + $Value.Substring(([string]$prefix.Root).Length)
        }
    }
    # Не передавать реальные имена пользователей в отчёте.
    return [regex]::Replace($Value, '(?i)\b[A-Z]:\\Users\\[^\\\s"/]+', '%WINDOWS_USER_HOME%')
}
function Public-Error {
    param([System.Exception] $ErrorObject)
    # Никогда не экспортируем реальные командные строки или секреты.
    $message = [string]$ErrorObject.Message
    $message = [regex]::Replace($message, '(?i)(access_token|refresh_token|id_token|authorization|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+', '$1=<СКРЫТО>')
    $message = [regex]::Replace($message, '(?i)\b[A-Z]:\\Users\\[^\\\s"/]+', '%WINDOWS_USER_HOME%')
    if ($message.Length -gt 180) { $message = $message.Substring(0, 180) }
    return ($ErrorObject.GetType().Name + ': ' + $message)
}

Write-Event 'Среда' 'START' 'PowerShell 7; чтение только метаданных'
$procCandidates = [System.Collections.Generic.List[object]]::new()
$processStats = [ordered]@{ codex = 0; antigravity = 0 }
$procStatus = 'NOT_TESTED'
try {
    Write-Event 'Запущенные процессы' 'START' 'Запрос Win32_Process.CommandLine'
    $processes = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
    foreach ($proc in $processes) {
        $name = [string]$proc.Name
        $line = [string]$proc.CommandLine
        $exe = [string]$proc.ExecutablePath
        $isCodex = (($name -match '(?i)codex') -or ($line -match '(?i)(?<![A-Za-z0-9_-])(?:codex|@openai/codex)(?![A-Za-z0-9_-])'))
        $isAntigravity = (($name -match '(?i)antigravity') -or ($line -match '(?i)(?<![A-Za-z0-9_-])(?:antigravity|agy)(?![A-Za-z0-9_-])'))
        if (-not ($isCodex -or $isAntigravity)) { continue }
        if ($isCodex) { $processStats.codex = [int]$processStats.codex + 1 }
        if ($isAntigravity) { $processStats.antigravity = [int]$processStats.antigravity + 1 }
        if ($procCandidates.Count -ge 40) { continue }
        $matchSource = if (($name -match '(?i)codex|antigravity|agy')) { 'process_name' } else { 'command_line' }
        # Только исполняемый файл/скрипт запуска; дополнительные аргументы никогда не сохраняются.
        $launchTarget = ''
        $targetMatch = [regex]::Match($line, '(?i)"([A-Z]:\\[^"\r\n]+\\(?:codex|antigravity|agy)\.(?:exe|cmd|ps1|js|mjs))"')
        if ($targetMatch.Success) { $launchTarget = Clean-Path $targetMatch.Groups[1].Value }
        $procCandidates.Add([ordered]@{
            pid = [int]$proc.ProcessId
            parent_pid = [int]$proc.ParentProcessId
            name = $name
            product = $(if ($isCodex -and $isAntigravity) { 'оба маркера' } elseif ($isCodex) { 'Codex' } else { 'Antigravity' })
            executable = Clean-Path $exe
            launch_target = $launchTarget
            matched_using = $matchSource
            launch_line_inspected = (-not [string]::IsNullOrEmpty($line))
            launch_line_exported = $false
            # НИКОГДА не сохранять $line: в ней могут быть ключи, cookies или токены.
        })
    }
    $procStatus = 'PASS'
    Write-Event 'Запущенные процессы' 'PASS' ('Проверено: {0}, Codex: {1}, Antigravity: {2}' -f $processes.Count, $processStats.codex, $processStats.antigravity)
} catch {
    $procStatus = 'PARTIAL'
    $errors.Add('PROCESS_QUERY_' + (Public-Error $_.Exception))
    Write-Event 'Запущенные процессы' 'PARTIAL' 'CIM недоступен; продолжена диагностика без командных строк'
}

Write-Event 'Исполняемые файлы' 'START' 'Get-Command и стандартные расположения'
$cmdResults = [ordered]@{}
foreach ($tool in @('pwsh.exe', 'git.exe', 'winget.exe', 'codex.exe', 'codex', 'agy.exe', 'agy', 'Antigravity.exe', 'chrome.exe', 'ollama.exe', 'nvidia-smi.exe')) {
    $hits = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($entry in @(Get-Command -Name $tool -All -ErrorAction SilentlyContinue | Select-Object -First 6)) {
            $source = if ($entry.PSObject.Properties['Path']) { [string]$entry.Path } else { [string]$entry.Source }
            $hits.Add([ordered]@{ command_type = [string]$entry.CommandType; path = Clean-Path $source })
        }
    } catch { }
    $cmdResults[$tool] = @($hits.ToArray())
}
$known = [System.Collections.Generic.List[object]]::new()
function Add-KnownPath {
    param([string] $Product, [AllowEmptyString()][string] $Root, [string] $Relative)
    if ([string]::IsNullOrWhiteSpace($Root)) { return }
    try {
        $absolute = Join-Path $Root $Relative
        if (Test-Path -LiteralPath $absolute -PathType Leaf) {
            $script:known.Add([ordered]@{ product = $Product; executable = Clean-Path $absolute })
        }
    } catch { }
}
$pf86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)', 'Process')
Add-KnownPath 'Git' $env:ProgramFiles 'Git\cmd\git.exe'
Add-KnownPath 'Git' $pf86 'Git\cmd\git.exe'
Add-KnownPath 'Git' $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe'
Add-KnownPath 'Codex' $env:LOCALAPPDATA 'Programs\Codex\Codex.exe'
Add-KnownPath 'Codex' $env:APPDATA 'npm\codex.cmd'
Add-KnownPath 'Codex' $env:APPDATA 'npm\codex.ps1'
Add-KnownPath 'Antigravity' $env:LOCALAPPDATA 'Programs\Antigravity\Antigravity.exe'
Add-KnownPath 'Antigravity' $env:LOCALAPPDATA 'Programs\Google Antigravity\Antigravity.exe'
Add-KnownPath 'Antigravity' $env:APPDATA 'npm\agy.cmd'
Add-KnownPath 'Antigravity' $env:APPDATA 'npm\agy.ps1'
Add-KnownPath 'PowerShell 7' $env:ProgramFiles 'PowerShell\7\pwsh.exe'
Add-KnownPath 'Chrome' $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'
Add-KnownPath 'Chrome' $pf86 'Google\Chrome\Application\chrome.exe'
Add-KnownPath 'Ollama' $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
Write-Event 'Исполняемые файлы' 'PASS' ('Известных путей: {0}' -f $known.Count)

Write-Event 'Установленные приложения' 'START' 'Только названия и версии'
$appx = [System.Collections.Generic.List[object]]::new()
if (Get-Command Get-AppxPackage -ErrorAction SilentlyContinue) {
    foreach ($pattern in @('*Codex*', '*OpenAI*', '*Antigravity*')) {
        try {
            foreach ($item in @(Get-AppxPackage -Name $pattern -ErrorAction Stop | Select-Object -First 20)) {
                $appx.Add([ordered]@{ name=[string]$item.Name; version=[string]$item.Version })
            }
        } catch { }
    }
}
$installed = [System.Collections.Generic.List[object]]::new()
foreach ($registryKey in @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)) {
    try {
        foreach ($item in @(Get-ItemProperty -Path $registryKey -ErrorAction SilentlyContinue)) {
            if (-not $item.PSObject.Properties['DisplayName']) { continue }
            $label = [string]$item.DisplayName
            if ($label -notmatch '(?i)Codex|OpenAI|Antigravity|Git for Windows|Google Chrome|Ollama|LM Studio') { continue }
            $version = if ($item.PSObject.Properties['DisplayVersion']) { [string]$item.DisplayVersion } else { '' }
            $installed.Add([ordered]@{ name=$label; version=$version })
            if ($installed.Count -ge 50) { break }
        }
    } catch { }
    if ($installed.Count -ge 50) { break }
}
Write-Event 'Установленные приложения' 'PASS' ('Appx: {0}; Registry: {1}' -f $appx.Count, $installed.Count)

Write-Event 'Видеокарта' 'START' 'Только NVIDIA metadata'
$gpu = [ordered]@{ status='NOT_AVAILABLE'; name=''; vram_mib=''; driver='' }
try {
    $nv = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $nv) {
        $lines = @(& $nv.Source '--query-gpu=name,memory.total,driver_version' '--format=csv,noheader,nounits' 2>$null)
        if ($LASTEXITCODE -eq 0 -and $lines.Count -ge 1) {
            $parts = ([string]$lines[0]).Split(',')
            if ($parts.Count -ge 3) {
                $gpu = [ordered]@{ status='DETECTED'; name=$parts[0].Trim(); vram_mib=$parts[1].Trim(); driver=$parts[2].Trim() }
            }
        }
    }
} catch { $errors.Add('GPU_METADATA_' + (Public-Error $_.Exception)) }
Write-Event 'Видеокарта' 'PASS' $gpu.status

$verdict = if ($procStatus -eq 'PASS') { 'PASS_READONLY_DISCOVERY' } else { 'PARTIAL' }
Write-Event 'Сканер' $verdict 'Секретные аргументы процессов не сохраняются'
$report = [ordered]@{
    schema = 'RAI_FABRIC_PROVIDER_DISCOVERY/2'
    utc = [DateTime]::UtcNow.ToString('o')
    verdict = $verdict
    powershell = $PSVersionTable.PSVersion.ToString()
    machine_os = 'Windows'
    process_search = [ordered]@{
        method = 'Win32_Process.CommandLine + Name + ExecutablePath'
        status = $procStatus
        inspected_processes = $(if ($procStatus -eq 'PASS') { $processes.Count } else { $null })
        matching_counts = $processStats
        candidates = @($procCandidates.ToArray())
        raw_command_lines_included = $false
    }
    commands = $cmdResults
    known_executables = @($known.ToArray())
    appx_packages = @($appx.ToArray())
    installed_programs = @($installed.ToArray())
    gpu = $gpu
    errors = @($errors.ToArray())
    restrictions = [ordered]@{
        profiles_or_tokens_read = $false
        process_command_lines_read_for_matching = $true
        process_command_lines_exported = $false
        model_calls = 0
        oauth_requests = 0
        shell_scripts_from_discovered_apps_executed = $false
        bpr40_modified = $false
    }
    next_cursor = 'RAI-FABRIC/09.7-E-PROCESS_DISCOVERY_RESULT_REVIEW'
}
[IO.File]::WriteAllText($OutputPath, (($report | ConvertTo-Json -Depth 12) + "`n"), $utf8)
$lines = @($events.ToArray() | ForEach-Object { $_ | ConvertTo-Json -Depth 6 -Compress })
[IO.File]::WriteAllLines($EventsPath, $lines, $utf8)
Write-Host ('Отчёт: ' + $OutputPath)
if ($verdict -eq 'PARTIAL') { exit 2 }
exit 0
