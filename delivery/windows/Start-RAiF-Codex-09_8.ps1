#requires -Version 7.0
# Rassvet AI Fabric — Codex App Server 09.8, только локальный handshake, без модели.
# Два входных файла: этот PS1 и RAiF-Codex-Handshake-09_8.zip в D:\ЗАГРУЗКИ.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$project = 'C:\GIT\Rassvet_AI_Fabric'
$downloads = 'D:\ЗАГРУЗКИ'
$zipName = 'RAiF-Codex-Handshake-09_8.zip'
$expectedZipHash = '7f02ed85b3c6afdfe44ce013a95f290a560558f82185bce1f56fe696e8e663b1'
$sourceZip = Join-Path $downloads $zipName
$runId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8)
$root = Join-Path $project ('.rai-fabric\windows-validation\runs\codex09_8_' + $runId)
$payloadRoot = Join-Path $root 'payload'
$reportsRoot = Join-Path $root 'reports'
$sandboxRoot = Join-Path $root 'sandbox'
$stepsPath = Join-Path $reportsRoot 'STEPS.jsonl'
$receiptPath = Join-Path $reportsRoot 'CHECKPOINT.json'
$resultZip = Join-Path $project ('RAiF-Windows-RESULT-CODEX-' + $runId + '.zip')
$utf8 = [Text.UTF8Encoding]::new($false)
$steps = [Collections.Generic.List[object]]::new()
$verifiedBundle = $false
$verifiedPayload = $false
$probeStatus = 'NOT_RUN'
$probeExitCode = $null
$code = 'NOT_STARTED'
$verdict = 'BLOCKED'
$exitCode = 2
function Add-Step {
    param([string]$Stage,[string]$State,[string]$Code)
    $e = [ordered]@{ utc=[DateTime]::UtcNow.ToString('o'); stage=$Stage; state=$State; code=$Code }
    $script:steps.Add($e)
    [IO.File]::AppendAllText($script:stepsPath, (($e | ConvertTo-Json -Compress -Depth 4) + "`n"), $script:utf8)
    Write-Host ('[{0}] {1}: {2}' -f $State,$Stage,$Code)
}
function Assert-NoReparse {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        $it = Get-Item -LiteralPath $Path -Force
        if (([int]$it.Attributes -band [int][IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw [InvalidOperationException]::new('REPARSE_BLOCKED')
        }
    }
}
function Write-Checkpoint {
    $probe = $null
    $probePath = Join-Path $script:reportsRoot 'PROBE.json'
    if (Test-Path -LiteralPath $probePath -PathType Leaf) {
        try { $probe = Get-Content -LiteralPath $probePath -Raw -Encoding utf8 | ConvertFrom-Json -Depth 20 } catch { }
    }
    $data = [ordered]@{
        schema = 'RAI_FABRIC_HOST_CODEX_HANDSHAKE_RESULT/1'
        stage = 'RAI-FABRIC/09.8-CODEX_APP_SERVER_NONINFERENCE_HANDSHAKE'
        verdict = $script:verdict
        code = $script:code
        observed_at_utc = [DateTime]::UtcNow.ToString('o')
        source_package_sha256 = $script:expectedZipHash
        source_package_verified = $script:verifiedBundle
        payload_verified = $script:verifiedPayload
        probe_status = $script:probeStatus
        probe_exit_code = $script:probeExitCode
        steps_recorded = $script:steps.Count
        probe = $probe
        result_location = 'C:\GIT\Rassvet_AI_Fabric\RAiF-Windows-RESULT-CODEX-*.zip'
        restrictions = [ordered]@{
            existing_codex_home_read = $false
            existing_codex_sessions_modified = $false
            external_model_calls_initiated = 0
            thread_started = $false
            turn_started = $false
            account_or_config_requested = $false
            oauth_performed = $false
            browser_automation = $false
            bpr40_modified = $false
            control_tower_modified = $false
            github_actions_launched = 0
            linux_used = $false
            raw_process_commands_exported = $false
            raw_stdio_messages_exported = $false
        }
        next_cursor = 'RAI-FABRIC/09.8-B-HOST_HANDSHAKE_RESULT_REVIEW'
    }
    [IO.File]::WriteAllText($script:receiptPath, (($data | ConvertTo-Json -Depth 25) + "`n"), $script:utf8)
}
function Test-BundleArchive {
    param([string]$Path)
    Add-Type -AssemblyName System.IO.Compression.ZipFile
    $archive = [IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $names = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\','/') })
        $allowed = @('manifest.json','tools/Probe-CodexAppServer.ps1')
        if ($names.Count -ne 2) { throw [IO.InvalidDataException]::new('UNEXPECTED_ZIP_CONTENTS') }
        foreach ($n in $names) {
            if ($n -notin $allowed -or $n.StartsWith('/') -or $n.Contains(':') -or
                $n.Contains('..') -or $n.Contains('\')) {
                throw [IO.InvalidDataException]::new('UNEXPECTED_ZIP_ENTRY')
            }
        }
        foreach ($entry in $archive.Entries) {
            if ($entry.Length -gt 250000) { throw [IO.InvalidDataException]::new('ZIP_ENTRY_TOO_LARGE') }
        }
    } finally { $archive.Dispose() }
}
function Save-ResultArchive {
    $reportFiles = @('STEPS.jsonl','CHECKPOINT.json','PROBE_STAGES.jsonl','PROBE.json') |
        ForEach-Object { Join-Path $script:reportsRoot $_ } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    if (@($reportFiles).Count -lt 2) { throw [IO.InvalidDataException]::new('NO_REPORTS_TO_PACKAGE') }
    Compress-Archive -LiteralPath $reportFiles -DestinationPath $script:resultZip -CompressionLevel Optimal -Force
}
if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'Требуется Windows и pwsh.exe 7.'
}
if (-not (Test-Path -LiteralPath $project -PathType Container)) {
    throw 'Не найден C:\GIT\Rassvet_AI_Fabric. Чужой проект автоматически не создаётся.'
}
foreach ($p in @('C:\GIT',$project,(Join-Path $project '.rai-fabric'),
    (Join-Path $project '.rai-fabric\windows-validation'),
    (Join-Path $project '.rai-fabric\windows-validation\runs'),$root)) { Assert-NoReparse $p }
[IO.Directory]::CreateDirectory($reportsRoot) | Out-Null
try {
    Add-Step 'environment' 'PASS' 'WINDOWS_PWSH7'
    Add-Step 'bundle' 'START' 'SHA256_PINNED'
    if (-not (Test-Path -LiteralPath $sourceZip -PathType Leaf)) {
        throw [IO.FileNotFoundException]::new('SOURCE_ZIP_NOT_FOUND')
    }
    if ((Get-FileHash -LiteralPath $sourceZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedZipHash) {
        throw [IO.InvalidDataException]::new('SOURCE_ZIP_SHA256_MISMATCH')
    }
    Test-BundleArchive $sourceZip
    $verifiedBundle = $true
    Add-Step 'bundle' 'PASS' 'ZIP_SHA256_AND_ENTRIES'

    [IO.Directory]::CreateDirectory($payloadRoot) | Out-Null
    [IO.Directory]::CreateDirectory($sandboxRoot) | Out-Null
    Expand-Archive -LiteralPath $sourceZip -DestinationPath $payloadRoot -ErrorAction Stop
    $manifestPath = Join-Path $payloadRoot 'manifest.json'
    $probePath = Join-Path $payloadRoot 'tools\Probe-CodexAppServer.ps1'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json -Depth 15
    if ($manifest.schema -ne 'RAI_FABRIC_CODEX_HANDSHAKE_PACKAGE/1') {
        throw [IO.InvalidDataException]::new('UNKNOWN_MANIFEST_SCHEMA')
    }
    if ($manifest.probe_path -ne 'tools/Probe-CodexAppServer.ps1') {
        throw [IO.InvalidDataException]::new('INVALID_PROBE_PATH')
    }
    if (-not (Test-Path -LiteralPath $probePath -PathType Leaf)) {
        throw [IO.FileNotFoundException]::new('PROBE_MISSING')
    }
    if ((Get-FileHash -LiteralPath $probePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$manifest.probe_sha256) {
        throw [IO.InvalidDataException]::new('PROBE_SHA256_MISMATCH')
    }
    $verifiedPayload = $true
    Add-Step 'payload' 'PASS' 'VERIFIED_STANDALONE_PROBE'

    Add-Step 'probe' 'START' 'ONLY_INITIALIZE_AND_INITIALIZED'
    # Сырой вывод не сохраняется вовсе: журналы пишет только проверенный код.
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $probePath -ReportsRoot $reportsRoot -SandboxRoot $sandboxRoot *> $null
    $probeExitCode = $LASTEXITCODE
    $probeReport = Join-Path $reportsRoot 'PROBE.json'
    if (-not (Test-Path -LiteralPath $probeReport -PathType Leaf)) {
        throw [IO.InvalidDataException]::new('PROBE_REPORT_MISSING')
    }
    $probe = Get-Content -LiteralPath $probeReport -Raw -Encoding utf8 | ConvertFrom-Json -Depth 20
    if ($probe.schema -ne 'RAI_FABRIC_CODEX_APP_SERVER_HANDSHAKE/1') {
        throw [IO.InvalidDataException]::new('PROBE_REPORT_SCHEMA_MISMATCH')
    }
    $probeStatus = [string]$probe.status
    if ($probeExitCode -eq 0 -and $probeStatus -eq 'PASS_WITH_SCOPE' -and $probe.initialized_response -and
        $probe.initialized_notification_sent -and $probe.provider_model_calls -eq 0) {
        $verdict = 'PASS_WITH_SCOPE'
        $code = 'APP_SERVER_JSONL_INITIALIZED'
        $exitCode = 0
        Add-Step 'probe' 'PASS' 'NONINFERENCE_HANDSHAKE'
    } else {
        $verdict = 'BLOCKED'
        $code = 'PROBE_NO_PASS'
        Add-Step 'probe' 'BLOCKED' 'CHECK_PROBE_JSON'
    }
}
catch {
    # Секреты, пути профиля, командные строки, значения исключений в ответ не добавляются.
    $code = $_.Exception.GetType().Name
    $verdict = 'BLOCKED'
    $exitCode = 2
    Add-Step 'execution' 'BLOCKED' $code
}
finally {
    try {
        Add-Step 'result_archive' 'START' 'PROJECT_ROOT_ZIP'
        Write-Checkpoint
        Save-ResultArchive
        Add-Step 'result_archive' 'PASS' 'PROJECT_ROOT_ZIP'
        Write-Checkpoint
        Save-ResultArchive
        Write-Host ('Результирующий ZIP: ' + $resultZip)
    } catch {
        Write-Host 'Не удалось сформировать ZIP результатов; отчёты остались в приватном runtime.'
        $exitCode = 3
    }
}
exit $exitCode
