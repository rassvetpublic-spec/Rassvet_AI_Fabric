#requires -Version 7.0
# Rassvet AI Fabric 09.8. Без моделей и без чтения существующего CODEX_HOME.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string] $ReportsRoot,
    [Parameter(Mandatory=$true)][string] $SandboxRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.Directory]::CreateDirectory($ReportsRoot) | Out-Null
[IO.Directory]::CreateDirectory($SandboxRoot) | Out-Null
$eventsPath = Join-Path $ReportsRoot 'PROBE_STAGES.jsonl'
$reportPath = Join-Path $ReportsRoot 'PROBE.json'
$events = [Collections.Generic.List[object]]::new()
$server = $null
$startTime = [DateTime]::UtcNow
$outcome = [ordered]@{
    schema = 'RAI_FABRIC_CODEX_APP_SERVER_HANDSHAKE/1'
    status = 'BLOCKED'
    code = 'NOT_STARTED'
    binary_found = $false
    binary_source = 'NONE'
    binary_size_bytes = $null
    binary_sha256 = $null
    binary_version = $null
    initialized_response = $false
    initialized_notification_sent = $false
    json_lines_received = 0
    skipped_nonmatching_lines = 0
    response_fields = [ordered]@{ userAgent = $false; platformFamily = $false; platformOs = $false }
    child_cleanup = 'NOT_STARTED'
    isolated_codex_home = $true
    existing_codex_home_read = $false
    methods_sent = @('initialize', 'initialized')
    thread_started = $false
    turn_started = $false
    account_or_config_requested = $false
    provider_model_calls = 0
    oauth_performed = $false
    existing_desktop_processes_touched = $false
    sampled_at_utc = $startTime.ToString('o')
    duration_ms = 0
}
function Add-ProbeStage {
    param([string]$Stage,[string]$State,[string]$Code)
    $ev = [ordered]@{ utc = [DateTime]::UtcNow.ToString('o'); stage=$Stage; state=$State; code=$Code }
    $script:events.Add($ev)
    [IO.File]::AppendAllText($script:eventsPath, (($ev | ConvertTo-Json -Compress -Depth 4) + "`n"), $script:utf8)
}
function Assert-NoReparse {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        $it = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if (([int]$it.Attributes -band [int][IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw [InvalidOperationException]::new('REPARSE_BLOCKED')
        }
    }
}
function Find-AllowlistedCodex {
    # Только codex.exe из каталога собственного приложения Codex; никаких node.exe/ChatGPT.exe.
    $root = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return $null }
    Assert-NoReparse $root
    $prefix = ([IO.Path]::GetFullPath($root).TrimEnd('\') + '\')
    $candidates = [Collections.Generic.List[object]]::new()
    try {
        $running = @(Get-CimInstance Win32_Process -Filter "Name = 'codex.exe'" -ErrorAction Stop)
        foreach ($proc in $running) {
            $path = [string]$proc.ExecutablePath
            if (-not [string]::IsNullOrWhiteSpace($path)) {
                $candidates.Add([pscustomobject]@{ path=$path; source='RUNNING_CODEX' })
            }
        }
    } catch { Add-ProbeStage 'process_metadata' 'PARTIAL' 'CIM_NOT_AVAILABLE' }
    $direct = Join-Path $root 'codex.exe'
    $candidates.Add([pscustomobject]@{ path=$direct; source='CODEX_INSTALL_DIR' })
    foreach ($sub in @(Get-ChildItem -LiteralPath $root -Directory -Force -ErrorAction SilentlyContinue | Select-Object -First 32)) {
        if ($sub.Name -match '^[0-9a-fA-F]{8,64}$' -and
            (([int]$sub.Attributes -band [int][IO.FileAttributes]::ReparsePoint) -eq 0)) {
            $candidates.Add([pscustomobject]@{ path=(Join-Path $sub.FullName 'codex.exe'); source='CODEX_INSTALL_DIR' })
        }
    }
    foreach ($entry in $candidates) {
        $candidate = [IO.Path]::GetFullPath([string]$entry.path)
        if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { continue }
        if ([IO.Path]::GetFileName($candidate) -ine 'codex.exe') { continue }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $file = Get-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue
        if ($null -eq $file) { continue }
        if (([int]$file.Attributes -band [int][IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
        $parent = Split-Path -Parent $candidate
        Assert-NoReparse $parent
        return [pscustomobject]@{ path=$candidate; file=$file; source=$entry.source }
    }
    return $null
}
try {
    if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSVersion.Major -lt 7) {
        throw [InvalidOperationException]::new('WINDOWS_PWSH7_REQUIRED')
    }
    Add-ProbeStage 'binary_discovery' 'START' 'ALLOWLIST_ONLY'
    if (-not $env:LOCALAPPDATA) { throw [InvalidOperationException]::new('LOCAL_APPDATA_MISSING') }
    $binary = Find-AllowlistedCodex
    if ($null -eq $binary) { throw [IO.FileNotFoundException]::new('CODEX_EXE_NOT_FOUND') }
    $outcome.binary_found = $true
    $outcome.binary_source = [string]$binary.source
    $outcome.binary_size_bytes = [long]$binary.file.Length
    $outcome.binary_sha256 = (Get-FileHash -LiteralPath $binary.path -Algorithm SHA256).Hash.ToLowerInvariant()
    try {
        $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($binary.path).FileVersion
        if ($version -and $version -match '^[a-zA-Z0-9 ._-]{1,64}$') { $outcome.binary_version = $version }
    } catch { }
    Add-ProbeStage 'binary_discovery' 'PASS' 'ALLOWLIST_CODEX_EXE'

    # Ни один существующий профиль/токен Codex не читается и не передаётся в дочерний процесс.
    $privateHome = Join-Path $SandboxRoot 'codex-home'
    foreach ($path in @($SandboxRoot,$privateHome)) { Assert-NoReparse $path }
    [IO.Directory]::CreateDirectory($privateHome) | Out-Null
    Add-ProbeStage 'sandbox' 'PASS' 'ISOLATED_CODEX_HOME'

    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = [string]$binary.path
    $psi.ArgumentList.Add('app-server')
    $psi.ArgumentList.Add('--listen')
    $psi.ArgumentList.Add('stdio://')
    $psi.WorkingDirectory = $SandboxRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    # Дочернему процессу передаётся allowlist переменных, не вся среда пользователя.
    $safeNames = @('PATH','SystemRoot','WINDIR','TEMP','TMP','LOCALAPPDATA','APPDATA',
                   'USERPROFILE','ProgramFiles','ProgramData','HOMEDRIVE','HOMEPATH')
    $allowedEnvironment = [ordered]@{}
    foreach ($name in $safeNames) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if (-not [string]::IsNullOrEmpty($value)) { $allowedEnvironment[$name] = $value }
    }
    $psi.Environment.Clear()
    foreach ($name in $allowedEnvironment.Keys) { $psi.Environment[$name] = $allowedEnvironment[$name] }
    $psi.Environment['CODEX_HOME'] = $privateHome
    $psi.Environment['CI'] = 'true'
    $psi.Environment['NO_COLOR'] = '1'
    $server = [Diagnostics.Process]::new()
    $server.StartInfo = $psi
    Add-ProbeStage 'child_start' 'START' 'APP_SERVER_STDIO_ONLY'
    if (-not $server.Start()) { throw [InvalidOperationException]::new('PROCESS_START_REJECTED') }
    $outcome.child_cleanup = 'RUNNING'
    # stderr потребляется асинхронно и не сохраняется: он может содержать приватные сведения.
    $server.BeginErrorReadLine()
    Add-ProbeStage 'child_start' 'PASS' 'OWN_CHILD_PROCESS'

    $hello = '{"method":"initialize","id":1,"params":{"clientInfo":{"name":"rassvet_ai_fabric","title":"Rassvet AI Fabric","version":"0.1.0"},"capabilities":{"experimentalApi":false}}}'
    $server.StandardInput.WriteLine($hello)
    $server.StandardInput.Flush()
    Add-ProbeStage 'initialize' 'SENT' 'JSONL_REQUEST_ID_1'
    $deadline = [DateTime]::UtcNow.AddSeconds(18)
    $received = $false
    while ([DateTime]::UtcNow -lt $deadline -and $outcome.json_lines_received -lt 96) {
        $remaining = [int][Math]::Max(1, ($deadline - [DateTime]::UtcNow).TotalMilliseconds)
        $pending = $server.StandardOutput.ReadLineAsync()
        if (-not $pending.Wait($remaining)) { throw [TimeoutException]::new('INITIALIZE_TIMEOUT') }
        $line = $pending.GetAwaiter().GetResult()
        if ($null -eq $line) { throw [IO.EndOfStreamException]::new('STDOUT_CLOSED') }
        $outcome.json_lines_received++
        if ($line.Length -gt 32768) { throw [IO.InvalidDataException]::new('OVERSIZED_PROTOCOL_FRAME') }
        try { $obj = ConvertFrom-Json -InputObject $line -AsHashtable -Depth 20 -ErrorAction Stop }
        catch { $outcome.skipped_nonmatching_lines++; continue }
        if (-not ($obj -is [System.Collections.IDictionary]) -or -not $obj.Contains('id') -or
            [string]$obj['id'] -ne '1') {
            $outcome.skipped_nonmatching_lines++
            continue
        }
        if ($obj.Contains('error')) { throw [InvalidOperationException]::new('INITIALIZE_REJECTED') }
        if (-not $obj.Contains('result') -or -not ($obj['result'] -is [System.Collections.IDictionary])) {
            throw [IO.InvalidDataException]::new('INVALID_INITIALIZE_RESPONSE')
        }
        $result = $obj['result']
        foreach ($key in @('userAgent','platformFamily','platformOs')) {
            $outcome.response_fields[$key] = $result.Contains($key)
        }
        $outcome.initialized_response = $true
        $received = $true
        Add-ProbeStage 'initialize_response' 'PASS' 'RESPONSE_ID_1'
        break
    }
    if (-not $received) { throw [TimeoutException]::new('INITIALIZE_RESPONSE_MISSING') }
    $server.StandardInput.WriteLine('{"method":"initialized"}')
    $server.StandardInput.Flush()
    $outcome.initialized_notification_sent = $true
    Add-ProbeStage 'initialized' 'SENT' 'NOTIFICATION_NO_ID'
    $outcome.status = 'PASS_WITH_SCOPE'
    $outcome.code = 'STDIO_HANDSHAKE_OK'
}
catch {
    # Исключение/текст ошибки дочернего процесса не сериализуются.
    $kind = $_.Exception.GetType().Name
    $allowed = @('FileNotFoundException','TimeoutException','EndOfStreamException',
                 'InvalidDataException','InvalidOperationException','Win32Exception','IOException')
    if ($kind -notin $allowed) { $kind = 'UnhandledException' }
    $outcome.status = 'BLOCKED'
    $outcome.code = $kind
    Add-ProbeStage 'handshake' 'BLOCKED' $kind
}
finally {
    if ($null -ne $server) {
        try {
            if ($outcome.child_cleanup -eq 'RUNNING') {
                try { $server.StandardInput.Close() } catch { }
                if ($server.WaitForExit(2500)) {
                    $outcome.child_cleanup = 'GRACEFUL_OR_EXITED'
                } else {
                    $server.Kill($true)
                    [void]$server.WaitForExit(2000)
                    $outcome.child_cleanup = 'FORCED_OWN_PROCESS_TREE'
                }
                Add-ProbeStage 'child_cleanup' 'PASS' $outcome.child_cleanup
            }
        } catch {
            $outcome.child_cleanup = 'UNVERIFIED'
            Add-ProbeStage 'child_cleanup' 'PARTIAL' 'CLEANUP_NOT_VERIFIED'
        } finally { $server.Dispose() }
    }
    if ($outcome.status -eq 'PASS_WITH_SCOPE' -and $outcome.child_cleanup -eq 'UNVERIFIED') {
        $outcome.status = 'PARTIAL'
        $outcome.code = 'CLEANUP_NOT_VERIFIED'
    }
    $outcome.duration_ms = [int]([DateTime]::UtcNow - $startTime).TotalMilliseconds
    [IO.File]::WriteAllText($reportPath, (($outcome | ConvertTo-Json -Depth 20) + "`n"), $utf8)
    Add-ProbeStage 'report' 'PASS' 'SANITIZED_JSON_ONLY'
}
if ($outcome.status -eq 'PASS_WITH_SCOPE') { exit 0 }
exit 2
