#requires -Version 7.0
# ОДИН реальный turn Codex, только авторизация ChatGPT и изолированный workspace.
# Никаких секретов в ZIP; не меняет действующий Codex Desktop и проекты.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$ProjectRoot = 'C:\GIT\Rassvet_AI_Fabric'
$ExpectedBundle = 'FFDADFA6F68EDF727A29D2AB7AE95D1EFC2D428641549FB04DE40118F7FFA48F'
$CodexExpected = 'D13914CED6C7AF174D8D638DB938284231227312104B06A25E9608C632A7DAEC'
$ID = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8)
$RuntimeBase = Join-Path $ProjectRoot '_RAIF_RUNTIME'
$RunRoot = Join-Path $RuntimeBase ('CODEX_LIVE_' + $ID)
$Payload = Join-Path $RunRoot 'payload'
$Workspace = Join-Path $RunRoot 'workspace'
$Logs = Join-Path $RunRoot 'logs'
$DbPath = Join-Path $RunRoot 'task.sqlite3'
$ResultZip = Join-Path $ProjectRoot ('RAiF-Windows-RESULT-CODEX-LIVE-' + $ID + '.zip')
$AttemptMarker = Join-Path $RuntimeBase 'ONE_REAL_TURN_10_0_CONSUMED.json'
$CodexHome = Join-Path $env:LOCALAPPDATA 'Rassvet_AI_Fabric\CodexPlanHome'
$TaskId = 'rai-live-' + $ID
$Utf8 = [Text.UTF8Encoding]::new($false)
$FinalStatus = 'BLOCKED'
$FinalCode = 'NOT_STARTED'
$ConsentConsumed = $false
$VerifiedBundle = $false
$AuthState = 'NOT_CHECKED'
$Stages = Join-Path $Logs 'STAGES.jsonl'
$Probed = Join-Path $Logs 'PROBE.json'
$Checkpoint = Join-Path $Logs 'CHECKPOINT.json'
$StartAt = [DateTime]::UtcNow

function AddStage([string]$Step, [string]$State, [string]$Code) {
    $entry = [ordered]@{
        utc = [DateTime]::UtcNow.ToString('o')
        stage = $Step; state = $State; code = $Code
        elapsed_ms = [int]([DateTime]::UtcNow - $StartAt).TotalMilliseconds
    }
    [IO.File]::AppendAllText($Stages, ($entry | ConvertTo-Json -Compress -Depth 5) + "`n", $Utf8)
}
function WriteJson([string]$Path, $Value) {
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 20) + "`n", $Utf8)
}
function RealPython {
    $candidates = [Collections.Generic.List[string]]::new()
    foreach ($item in @(Get-Command python -All -ErrorAction SilentlyContinue)) {
        if ($item.Source -and $item.Source.EndsWith('.exe')) { [void]$candidates.Add($item.Source) }
    }
    foreach ($v in @('Python313','Python312','Python311')) {
        [void]$candidates.Add((Join-Path $env:LOCALAPPDATA ("Programs\Python\" + $v + "\python.exe")))
    }
    foreach ($path in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        try {
            $found = (& $path -I -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null | Out-String).Trim()
            if ($LASTEXITCODE -eq 0 -and $found -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 11) {
                return $path
            }
        } catch { }
    }
    throw [InvalidOperationException]::new('NO_VERIFIED_PYTHON_3_11')
}
function PinnedCodex {
    $candidates = [Collections.Generic.List[string]]::new()
    foreach ($p in @(Get-CimInstance Win32_Process -Filter "Name='codex.exe'" -ErrorAction SilentlyContinue)) {
        if ($p.ExecutablePath) { [void]$candidates.Add([string]$p.ExecutablePath) }
    }
    [void]$candidates.Add((Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin\codex.exe'))
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        if ([IO.Path]::GetFileName($candidate) -ine 'codex.exe') { continue }
        if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash -eq $CodexExpected) { return $candidate }
    }
    throw [InvalidOperationException]::new('PINNED_CODEX_BINARY_NOT_FOUND_OR_UPDATED')
}
function ChatGPTLoginStatus([string]$Binary) {
    # Захватываем только в памяти; реальный вывод может включать приватную информацию.
    $msg = (& $Binary login status 2>&1 | Out-String)
    if ($LASTEXITCODE -eq 0 -and $msg -match 'Logged in using ChatGPT') { return $true }
    return $false
}

if (-not $IsWindows -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'Требуется Windows и PowerShell 7'
}
if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
    throw 'Корень C:\GIT\Rassvet_AI_Fabric отсутствует'
}
foreach ($item in @($ProjectRoot)) {
    if ((Get-Item -LiteralPath $item).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Корень проекта не может быть junction/symlink'
    }
}
if ((Test-Path -LiteralPath $RuntimeBase) -and
    ((Get-Item -LiteralPath $RuntimeBase).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Служебный каталог Fabric не может быть junction/symlink'
}
New-Item -ItemType Directory -Path $RuntimeBase,$RunRoot,$Payload,$Workspace,$Logs -Force | Out-Null
$SensitiveEnv = @('OPENAI_API_KEY','CODEX_API_KEY','CODEX_ACCESS_TOKEN','ACCESS_TOKEN',
                  'OPENAI_BASE_URL','OPENAI_ORG_ID','OPENAI_PROJECT_ID','AZURE_OPENAI_API_KEY',
                  'GEMINI_API_KEY','GOOGLE_API_KEY','GITHUB_TOKEN','GH_TOKEN','ANTHROPIC_API_KEY')
$OldEnv = @{}
$PreviousCodexHome = [Environment]::GetEnvironmentVariable('CODEX_HOME','Process')
foreach ($name in $SensitiveEnv) {
    $OldEnv[$name] = [Environment]::GetEnvironmentVariable($name,'Process')
    [Environment]::SetEnvironmentVariable($name,$null,'Process')
}
$env:CODEX_HOME = $CodexHome
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

try {
    AddStage 'preflight' 'START' 'WINDOWS_PWSH7'
    if (Test-Path -LiteralPath $AttemptMarker) {
        throw [InvalidOperationException]::new('ONE_TURN_ALREADY_CONSUMED_NO_RETRY')
    }
    AddStage 'preflight' 'PASS' 'ONE_TURN_MARKER_ABSENT'

    AddStage 'bundle' 'START' 'PINNED_ZIP_SHA256'
    $candidates = @(Get-ChildItem -LiteralPath $PSScriptRoot -File -Filter 'RAiF-Codex-Live-10_0*.zip')
    $source = $null
    foreach ($f in $candidates) {
        if ((Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash -eq $ExpectedBundle) {
            $source = $f.FullName; break
        }
    }
    if (-not $source) { throw [InvalidOperationException]::new('BUNDLE_HASH_MISMATCH_OR_NOT_FOUND') }
    Add-Type -AssemblyName System.IO.Compression
    $archive = [IO.Compression.ZipFile]::OpenRead($source)
    try {
        $names = @($archive.Entries | ForEach-Object FullName | Sort-Object)
        $expected = @('MANIFEST.json','src/rai_fabric/__init__.py',
                      'src/rai_fabric/codex_live_executor.py',
                      'src/rai_fabric/codex_real_transport.py','src/rai_fabric/store.py',
                      'tools/host_entry.py') | Sort-Object
        if (($names -join '|') -ne ($expected -join '|')) {
            throw [InvalidOperationException]::new('BUNDLE_UNEXPECTED_MEMBERS')
        }
    } finally { $archive.Dispose() }
    Expand-Archive -LiteralPath $source -DestinationPath $Payload -Force
    $manifest = Get-Content -LiteralPath (Join-Path $Payload 'MANIFEST.json') -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    if ($manifest.schema -ne 'RAIF_LIVE_ONE_TURN_BUNDLE/1' -or $manifest.source_commit -ne 'b0f54f1466742d202746301716f7a6425a32b1d0') {
        throw [InvalidOperationException]::new('BUNDLE_MANIFEST_INVALID')
    }
    foreach ($key in $manifest.file_sha256.Keys) {
        $candidate = Join-Path $Payload $key
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf) -or
            (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$manifest.file_sha256[$key]) {
            throw [InvalidOperationException]::new('BUNDLE_FILE_SHA_MISMATCH')
        }
    }
    $VerifiedBundle = $true
    AddStage 'bundle' 'PASS' 'SHA256_ALL_FILES'

    AddStage 'python' 'START' 'VALIDATE_REAL_INTERPRETER'
    $python = RealPython
    AddStage 'python' 'PASS' 'REAL_PYTHON_3_11_PLUS'
    AddStage 'codex' 'START' 'PINNED_BINARY'
    $binary = PinnedCodex
    AddStage 'codex' 'PASS' 'CODEX_BINARY_VERIFIED'

    AddStage 'auth' 'START' 'ISOLATED_CHATGPT_PLAN_LOGIN'
    New-Item -ItemType Directory -Path $CodexHome -Force | Out-Null
    if ((Get-Item -LiteralPath $CodexHome).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw [InvalidOperationException]::new('CODEX_HOME_SYMLINK_BLOCKED')
    }
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe $CodexHome /inheritance:r /grant:r ('*' + $sid + ':(OI)(CI)F') /T /C 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { throw [InvalidOperationException]::new('CODEX_HOME_ACL_FAILED') }
    if (-not (ChatGPTLoginStatus $binary)) {
        # Не пишем stdout/stderr команды login в журналы: код входа может быть секретным.
        Write-Host 'Требуется однократный вход ChatGPT для отдельного профиля Fabric.'
        Write-Host 'Заверши авторизацию в открывшемся браузере; пароли и коды сюда не присылай.'
        & $binary login
        if ($LASTEXITCODE -ne 0) { throw [InvalidOperationException]::new('CODEX_CHATGPT_LOGIN_FAILED') }
    }
    if (-not (ChatGPTLoginStatus $binary)) {
        throw [InvalidOperationException]::new('CHATGPT_LOGIN_NOT_CONFIRMED_NO_API_FALLBACK')
    }
    $AuthState = 'CHATGPT_PLAN_CLI_SIGNED_IN'
    AddStage 'auth' 'PASS' 'CHATGPT_ONLY_NO_API_KEY'

    AddStage 'queue' 'START' 'CREATE_ISOLATED_SQLITE_TASK'
    $entry = Join-Path $Payload 'tools\host_entry.py'
    $initResult = (& $python -I -B $entry init --db $DbPath --workspace $Workspace --task-id $TaskId 2>$null | Out-String)
    if ($LASTEXITCODE -ne 0 -or -not $initResult) { throw [InvalidOperationException]::new('SQLITE_SUBMIT_FAILED') }
    $queue = $initResult | ConvertFrom-Json -AsHashtable
    if ($queue.status -ne 'QUEUED' -or $queue.provider -ne 'codex-app') {
        throw [InvalidOperationException]::new('QUEUE_NOT_READY')
    }
    AddStage 'queue' 'PASS' 'EXACT_ONE_CODEX_APP_TASK'

    AddStage 'consent' 'START' 'PERSIST_ONE_TIME_MARKER'
    # Даже если сеть прервётся, вторую модельную попытку автоматически не выполняем.
    $markerText = @{ schema='RAIF_ONE_LIVE_TURN_CONSENT/1'; utc=[DateTime]::UtcNow.ToString('o');
                     task_id=$TaskId; verdict='ATTEMPT_RESERVED_NO_AUTORETRY' } | ConvertTo-Json -Compress
    $bytes = $Utf8.GetBytes($markerText + "`n")
    $stream = [IO.File]::Open($AttemptMarker,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
    $ConsentConsumed = $true
    AddStage 'consent' 'PASS' 'ONE_TIME_CONSENT_RESERVED'

    AddStage 'codex_live' 'START' 'ONE_TURN_NO_TOOL_APPROVAL'
    $argsLive = @('-I','-B',$entry,'run','--db',$DbPath,'--workspace',$Workspace,
                  '--task-id',$TaskId,'--binary',$binary,'--codex-home',$CodexHome,
                  '--expected-sha256',$CodexExpected,'--timeout','120','--consent-one-turn')
    $raw = (& $python @argsLive 2>$null | Out-String)
    $LiveExit = $LASTEXITCODE
    if (-not $raw) { throw [InvalidOperationException]::new('CODEX_LIVE_NO_REPORT') }
    $result = $raw | ConvertFrom-Json -AsHashtable
    $safe = [ordered]@{}
    foreach ($key in @('status','code','task_id','source_created','model_turn_sent',
                       'model_turn_started','model_turn_completed','checkpoint')) {
        if ($result.ContainsKey($key)) { $safe[$key]=$result[$key] }
    }
    WriteJson $Probed $safe
    if ($LiveExit -ne 0 -or $result.status -ne 'COMPLETE') {
        $FinalCode = [string]$result.code
        throw [InvalidOperationException]::new('CODEX_LIVE_RESULT_BLOCKED')
    }
    $FinalStatus = 'PASS_WITH_SCOPE'
    $FinalCode = 'ONE_REAL_TURN_AND_LOCAL_TESTS_PASS'
    AddStage 'codex_live' 'PASS' 'ONE_TURN_THREE_TESTS'
} catch {
    $FinalStatus = 'BLOCKED'
    if ($FinalCode -eq 'NOT_STARTED') { $FinalCode = 'HOST_STAGE_BLOCKED' }
    AddStage 'host' 'BLOCKED' $_.Exception.GetType().Name
} finally {
    [Environment]::SetEnvironmentVariable('CODEX_HOME',$PreviousCodexHome,'Process')
    foreach ($name in $SensitiveEnv) {
        [Environment]::SetEnvironmentVariable($name,$OldEnv[$name],'Process')
    }
    AddStage 'checkpoint' 'START' 'SAFE_METADATA_ONLY'
    $receipt = [ordered]@{
        schema='RAIF_WINDOWS_FIRST_LIVE_TURN/1'; date=[DateTime]::UtcNow.ToString('o')
        status=$FinalStatus; code=$FinalCode; task_id=$TaskId
        source_zip_verified=$VerifiedBundle; consent_consumed=$ConsentConsumed
        auth_status=$AuthState; api_key_fallback_enabled=$false
        user_projects_touched=$false; bpr40_changed=$false
        model_turn_limit='one turn/start; no automatic retry'
        result_folder='C:\GIT\Rassvet_AI_Fabric'
        cursor='RAI-FABRIC/10.0-B-ONE_REAL_TURN_HOST_RESULT_REVIEW'
    }
    WriteJson $Checkpoint $receipt
    AddStage 'checkpoint' 'PASS' 'REDACTED'
    AddStage 'zip' 'START' 'RESULT_PROJECT_ROOT'
    $pack = @(Get-ChildItem -LiteralPath $Logs -File | Where-Object {
        $_.Name -in @('CHECKPOINT.json','PROBE.json','STAGES.jsonl')
    } | ForEach-Object FullName)
    foreach ($file in @('arithmetic.py','test_arithmetic.py')) {
        $path = Join-Path $Workspace $file
        if (Test-Path -LiteralPath $path -PathType Leaf) { $pack += $path }
    }
    Compress-Archive -LiteralPath $pack -DestinationPath $ResultZip -CompressionLevel Optimal -Force
    AddStage 'zip' 'PASS' 'RESULT_ARCHIVE_WRITTEN'
    Compress-Archive -LiteralPath $pack -DestinationPath $ResultZip -CompressionLevel Optimal -Force
    Write-Host "ИТОГОВЫЙ ZIP: $ResultZip"
    Write-Host "СТАТУС: $FinalStatus"
}
if ($FinalStatus -eq 'PASS_WITH_SCOPE') { exit 0 }
exit 3
