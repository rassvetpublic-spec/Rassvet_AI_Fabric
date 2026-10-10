#requires -Version 7.0
# Rassvet AI Fabric 09.9-C — исправленный thread/start без turn/start.
# Ни действующие Codex-сессии, ни другие проекты не изменяются.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$ProjectRoot = 'C:\GIT\Rassvet_AI_Fabric'
$SourceHash = '35EA93400C314777383880490942E85E55DAA694025B24CA94921A5F0A510A98'
$ModuleHash = 'BF81F9BC5771A03122B20727EB598F85D8560702993B9763FDB87F79239045BA'
$CodexHash = 'D13914CED6C7AF174D8D638DB938284231227312104B06A25E9608C632A7DAEC'
$Identifier = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8)
$RunRoot = Join-Path $ProjectRoot ("_RAIF_RUNTIME\CODEX_THREAD_09_9C_" + $Identifier)
$LogDir = Join-Path $RunRoot 'logs'
$PayloadDir = Join-Path $RunRoot 'payload'
$Workspace = Join-Path $RunRoot 'workspace'
$ResultZip = Join-Path $ProjectRoot ("RAiF-Windows-RESULT-CODEX-THREAD-09_9C-" + $Identifier + '.zip')
$Utf8 = [Text.UTF8Encoding]::new($false)
$FinalStatus = 'BLOCKED'
$FinalCode = 'NOT_STARTED'
$PythonExit = $null
$ProbeStatus = 'NOT_RUN'
$VerifiedBundle = $false
$StepLog = Join-Path $LogDir 'STAGES.jsonl'
$ProbeFile = Join-Path $LogDir 'PROBE.json'
$ResultOut = Join-Path $LogDir 'CHECKPOINT.json'

function Stage([string]$Step, [string]$State, [string]$Code) {
    $event = [ordered]@{ utc = [DateTime]::UtcNow.ToString('o'); stage = $Step; state = $State; code = $Code }
    [IO.File]::AppendAllText($StepLog, (($event | ConvertTo-Json -Compress -Depth 5) + "`n"), $Utf8)
}
function WriteJson($Path, $Value) {
    [IO.File]::WriteAllText($Path, (($Value | ConvertTo-Json -Depth 16) + "`n"), $Utf8)
}
function ResolveRealPython {
    $candidates = [Collections.Generic.List[string]]::new()
    foreach ($command in @(Get-Command python -All -ErrorAction SilentlyContinue)) {
        if ($null -ne $command -and $command.Source -and $command.Source.EndsWith('.exe')) {
            [void]$candidates.Add($command.Source)
        }
    }
    foreach ($version in @('Python313','Python312','Python311')) {
        $candidate = Join-Path $env:LOCALAPPDATA ("Programs\Python\" + $version + "\python.exe")
        [void]$candidates.Add($candidate)
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            $versionText = (& $candidate -I -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null | Out-String).Trim()
            if ($LASTEXITCODE -eq 0 -and $versionText -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 11) {
                return $candidate
            }
        } catch { }
    }
    throw [InvalidOperationException]::new('PYTHON_EXECUTABLE_NOT_VERIFIED')
}
function ResolvePinnedCodex {
    $candidates = [Collections.Generic.List[string]]::new()
    try {
        foreach ($item in @(Get-CimInstance Win32_Process -Filter "Name='codex.exe'" -ErrorAction Stop)) {
            if ($null -ne $item.ExecutablePath -and $item.ExecutablePath) {
                [void]$candidates.Add([string]$item.ExecutablePath)
            }
        }
    } catch { }
    [void]$candidates.Add((Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin\codex.exe'))
    $sawExe = $false
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        if ([IO.Path]::GetFileName($candidate) -ine 'codex.exe') { continue }
        $sawExe = $true
        try {
            if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash -eq $CodexHash) {
                return $candidate
            }
        } catch { }
    }
    if ($sawExe) { throw [InvalidOperationException]::new('CODEX_BINARY_VERSION_DRIFT') }
    throw [IO.FileNotFoundException]::new('CODEX_EXE_NOT_FOUND')
}

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw 'Отсутствует корень проекта C:\GIT\Rassvet_AI_Fabric'
}
New-Item -ItemType Directory -Path $LogDir,$PayloadDir,$Workspace -Force | Out-Null
try {
    Stage 'environment' 'START' 'PWSH7_WINDOWS'
    if (-not $IsWindows -or $PSVersionTable.PSVersion.Major -lt 7) { throw [InvalidOperationException]::new('WINDOWS_PWSH7_REQUIRED') }
    Stage 'environment' 'PASS' 'PWSH7_WINDOWS'

    Stage 'bundle' 'START' 'SHA256_ALLOWLIST'
    $bundles = @(Get-ChildItem -LiteralPath $PSScriptRoot -File -Filter 'RAiF-Codex-Thread-09_9C*.zip' -ErrorAction Stop)
    $bundle = $null
    foreach ($item in $bundles) {
        if ((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash -eq $SourceHash) {
            $bundle = $item.FullName
            break
        }
    }
    if ($null -eq $bundle) { throw [IO.FileNotFoundException]::new('EXPECTED_BUNDLE_SHA256_NOT_FOUND') }
    Add-Type -AssemblyName System.IO.Compression
    $read = [IO.Compression.ZipFile]::OpenRead($bundle)
    try {
        $members = @($read.Entries | ForEach-Object FullName | Sort-Object)
        if ($members.Count -ne 2 -or $members[0] -ne 'MANIFEST.json' -or $members[1] -ne 'probe/codex_real_transport.py') {
            throw [IO.InvalidDataException]::new('BUNDLE_MEMBERS_UNEXPECTED')
        }
    } finally { $read.Dispose() }
    Expand-Archive -LiteralPath $bundle -DestinationPath $PayloadDir -Force
    $manifestPath = Join-Path $PayloadDir 'MANIFEST.json'
    $scriptPath = Join-Path $PayloadDir 'probe\codex_real_transport.py'
    if ((Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash -ne $ModuleHash) {
        throw [IO.InvalidDataException]::new('MODULE_SHA256_INVALID')
    }
    $config = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    if ($config.schema -ne 'RAI_FABRIC_CODEX_THREAD_BUNDLE/1' -or $config.file_sha256.ToUpperInvariant() -ne $ModuleHash) {
        throw [IO.InvalidDataException]::new('BUNDLE_MANIFEST_INVALID')
    }
    $VerifiedBundle = $true
    Stage 'bundle' 'PASS' 'SHA256_ALLOWLIST'

    Stage 'python' 'START' 'REAL_PYTHON_SEARCH'
    $python = ResolveRealPython
    Stage 'python' 'PASS' 'PYTHON_3_11_OR_LATER'

    Stage 'codex' 'START' 'RUNNING_PROCESS_PATH_AND_PIN'
    $binary = ResolvePinnedCodex
    Stage 'codex' 'PASS' 'EXACT_BINARY_SHA256'

    Stage 'rpc' 'START' 'INITIALIZE_AND_THREAD_START_NO_TURN'
    $rawResult = (& $python -I -B $scriptPath --binary $binary --workspace $Workspace --mode thread --timeout 25 --expected-sha256 $CodexHash 2>$null | Out-String).Trim()
    $PythonExit = $LASTEXITCODE
    if (-not $rawResult) { throw [IO.InvalidDataException]::new('PROBE_NO_JSON') }
    $parsed = $rawResult | ConvertFrom-Json -AsHashtable
    if ($parsed.schema -ne 'RAI_FABRIC_CODEX_REAL_TRANSPORT/1') {
        throw [IO.InvalidDataException]::new('PROBE_SCHEMA_INVALID')
    }
    # Только разрешённые поля. Никаких сырых RPC, stdout/stderr и путей профиля.
    $safe = [ordered]@{}
    foreach ($key in @('schema','status','code','stage','mode','initialize_response','initialized_sent',
                       'thread_created','thread_id_sha256_prefix','method_names_sent','rpc_error_code','notification_count',
                       'frames_received','no_turn_start_sent','no_oauth_performed','no_api_key_in_child_env',
                       'child_cleanup','duration_ms')) {
        if ($parsed.ContainsKey($key)) { $safe[$key] = $parsed[$key] }
    }
    WriteJson $ProbeFile $safe
    $ProbeStatus = [string]$parsed.status
    if ($PythonExit -ne 0 -or $parsed.status -ne 'PASS_WITH_SCOPE') {
        $FinalCode = [string]$parsed.code
        Stage 'rpc' 'BLOCKED' 'PROBE_RETURNED_BLOCKED'
    } else {
        if ($parsed.thread_created -ne $true -or $parsed.no_turn_start_sent -ne $true -or
            $parsed.no_oauth_performed -ne $true -or
            @($parsed.method_names_sent | Where-Object { $_ -eq 'turn/start' }).Count -ne 0) {
            throw [IO.InvalidDataException]::new('PROBE_CONTRACT_NOT_MET')
        }
        $FinalStatus = 'PASS_WITH_SCOPE'
        $FinalCode = 'THREAD_CREATED_NO_TURN'
        Stage 'rpc' 'PASS' 'THREAD_CREATED_NO_TURN'
    }
} catch {
    $FinalStatus = 'BLOCKED'
    if ($FinalCode -eq 'NOT_STARTED') { $FinalCode = 'LAUNCHER_STAGE_FAILED' }
    Stage 'launch' 'BLOCKED' ($_.Exception.GetType().Name)
} finally {
    Stage 'report' 'START' 'SANITIZED_CHECKPOINT'
    $receipt = [ordered]@{
        schema = 'RAI_FABRIC_CODEX_THREAD_HOST_RESULT/1'
        stage = 'RAI-FABRIC/09.9-WINDOWS_THREAD_START_NONINFERENCE'
        verdict = $FinalStatus
        code = $FinalCode
        observed_at_utc = [DateTime]::UtcNow.ToString('o')
        source_zip_sha256_verified = $VerifiedBundle
        original_codex_binary_sha256 = $CodexHash.ToLowerInvariant()
        probe_verdict = $ProbeStatus
        probe_exit_code = $PythonExit
        no_turn_start_intended = $true
        no_oauth_intended = $true
        user_projects_modified = $false
        github_actions_runs = 0
        bpr40_mutated = $false
        cursor = 'RAI-FABRIC/09.9-B-REAL_THREAD_HOST_RESULT_REVIEW'
    }
    WriteJson $ResultOut $receipt
    Stage 'report' 'PASS' 'SANITIZED_CHECKPOINT'
    Stage 'zip' 'START' 'PROJECT_ROOT'
    $pack = @(Get-ChildItem -LiteralPath $LogDir -File | Where-Object { $_.Name -in @('CHECKPOINT.json','PROBE.json','STAGES.jsonl') } | ForEach-Object FullName)
    Compress-Archive -LiteralPath $pack -DestinationPath $ResultZip -CompressionLevel Optimal -Force
    Stage 'zip' 'PASS' 'PROJECT_ROOT'
    # Второй проход включает финальное событие упаковки в самом ZIP.
    Compress-Archive -LiteralPath $pack -DestinationPath $ResultZip -CompressionLevel Optimal -Force
    Write-Host "Результат: $ResultZip"
    Write-Host "Статус: $FinalStatus"
}
if ($FinalStatus -eq 'PASS_WITH_SCOPE') { exit 0 }
exit 3
