#requires -Version 5.1
<#
RAiF / 10.1B: Windows-only host acceptance of an EXISTING pinned clone.
Default: inspect only. -Run: run 20 targeted tests, full offline unittest suite
and one deterministic owned mock. Does not clone, fetch, push, merge,
change tracked source, start Codex/Antigravity, or trigger CI.
Report: STAGES.jsonl, CURSOR.json, CHECKPOINT.json, SUMMARY.json.
Raw stdout, stderr, OAuth contents and local user profile paths are not logged.
#>
[CmdletBinding()]
param([switch]$Run)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:target = 'C:\GIT\Rassvet_AI_Fabric'
$script:repoUrl = 'https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric.git'
$script:branch = 'raif-10-1-worktree-offline-20261010'
$script:pin = 'a0daf08375b70d202b3dc7b5ab51f894e87d9ae0'
$script:codeSha = '69380fc864bbd2106ee8afd0e962bc165bbd19b0c22856add30d9883e2013bfc'
$script:testSha = '14c3e0cefb59a8d4086138442f94b8fe84ebcca6e438f19c87b11d85a81306fd'
$script:demoSha = '9b2dcc12c6121b8e9fc32183e49f0995e8c9369bb56c94b953d9dc1433259fd1'
$script:utf8 = [Text.UTF8Encoding]::new($false)
$script:cursor = 'RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION'
$script:lastStage = 'NOT_STARTED'
$script:finalVerdict = 'BLOCKED'
$script:finalCode = 'NOT_STARTED'
$script:stages = @()
$script:auditSafe = $false
$script:mode = if ($Run) { 'RUN_LOCAL_TESTS' } else { 'INSPECT_ONLY' }
$script:runId = 'RAIF_10_1B_' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '_' + [Guid]::NewGuid().ToString('N').Substring(0,12)
$script:python = $null
$script:gitExe = $null
$script:gitFlags = @('-c','credential.helper=', '-c','core.fsmonitor=false', '-c','core.autocrlf=false',
    '-c','core.safecrlf=true', '-c','core.sparseCheckout=false', '-c','protocol.ext.allow=never')
$script:results = [ordered]@{targeted=$null; full=$null; mock=$null}
$script:audit = $null
$script:allowedNext = 'RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE'
$script:restoreGitEnv = @{}

function Block([string]$Code) { throw [InvalidOperationException]::new($Code) }
function Assert-NoReparse([string]$PathValue) {
    $p = [IO.Path]::GetFullPath($PathValue)
    while ($true) {
        if (Test-Path -LiteralPath $p) {
            if (([IO.File]::GetAttributes($p) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                Block 'REPARSE_POINT_BLOCKED'
            }
        }
        $next = [IO.Path]::GetDirectoryName($p.TrimEnd('\'))
        if ([string]::IsNullOrWhiteSpace($next) -or $next -eq $p) { break }
        $p = $next
    }
}
function Sha256String([string]$StringValue) {
    $s = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($s.ComputeHash($script:utf8.GetBytes($StringValue)))).Replace('-','').ToLowerInvariant() }
    finally { $s.Dispose() }
}
function AtomicFile([string]$TargetFile, [string]$Content) {
    Assert-NoReparse $TargetFile
    $tmp = Join-Path ([IO.Path]::GetDirectoryName($TargetFile)) ('.' + [IO.Path]::GetFileName($TargetFile) + '.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $bytes = $script:utf8.GetBytes($Content)
    try {
        $s = [IO.FileStream]::new($tmp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write,
            [IO.FileShare]::None, 4096, [IO.FileOptions]::WriteThrough)
        try { $s.Write($bytes,0,$bytes.Length); $s.Flush($true) }
        finally { $s.Dispose() }
        Assert-NoReparse $TargetFile
        if ([IO.File]::Exists($TargetFile)) { [IO.File]::Replace($tmp,$TargetFile,$null) }
        else { [IO.File]::Move($tmp,$TargetFile) }
    } finally { if ([IO.File]::Exists($tmp)) { [IO.File]::Delete($tmp) } }
}
function Checkpoint([string]$Status, [string]$Code) {
    $doc = [ordered]@{
        schema='RAI_FABRIC_HOST_10_1B_CHECKPOINT/1'
        utc=[DateTime]::UtcNow.ToString('o')
        run_id=$script:runId
        stage='RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE'
        last_stage=$script:lastStage
        cursor=$script:cursor
        verdict=$Status
        code=$Code
        mode=$script:mode
        source_repository='rassvetpublic-spec/Rassvet_AI_Fabric'
        pinned_branch=$script:branch
        pinned_sha=$script:pin
        host_os='Windows'
        model_turns=0
        github_actions=0
        pushes=0
        merges=0
        source_mutations=0
        results=$script:results
        audit_dir=('%LOCALAPPDATA%\Rassvet_AI_Fabric\host_qa\' + $script:runId)
        note='PASS_WITH_SCOPE означает локальную offline QA; не выдаёт разрешения merge/модельного turn.'
    }
    $doc['sha256'] = Sha256String ($doc | ConvertTo-Json -Compress -Depth 10)
    AtomicFile (Join-Path $script:audit 'CHECKPOINT.json') (($doc | ConvertTo-Json -Depth 10) + "`n")
}
function Event([string]$Status, [string]$Stage, [string]$Code, [string]$Next) {
    foreach ($v in @($Status,$Stage,$Code)) {
        if ($v -notmatch '^[A-Z0-9_\-]{1,80}$') { Block 'UNSAFE_EVENT_VALUE' }
    }
    if ($Next -notmatch '^RAI-FABRIC/[A-Z0-9_.\-]+$') { Block 'INVALID_CURSOR' }
    $script:lastStage = $Stage
    $script:cursor = $Next
    $ev = [ordered]@{utc=[DateTime]::UtcNow.ToString('o');run_id=$script:runId;
        stage=$Stage;verdict=$Status;code=$Code;cursor=$Next}
    Assert-NoReparse $script:audit
    $bytes = $script:utf8.GetBytes(($ev | ConvertTo-Json -Compress) + "`n")
    $handle = [IO.FileStream]::new((Join-Path $script:audit 'STAGES.jsonl'),[IO.FileMode]::Append,
        [IO.FileAccess]::Write,[IO.FileShare]::Read,4096,[IO.FileOptions]::WriteThrough)
    try { $handle.Write($bytes,0,$bytes.Length);$handle.Flush($true) }
    finally { $handle.Dispose() }
    AtomicFile (Join-Path $script:audit 'CURSOR.json') (([ordered]@{schema='RAIF_CURSOR/1';
        run_id=$script:runId;stage=$Stage;verdict=$Status;code=$Code;cursor=$Next} | ConvertTo-Json -Depth 5) + "`n")
    Checkpoint 'PARTIAL' $Code
    Write-Host ('[{0}] {1}: {2} -> {3}' -f $Status,$Stage,$Code,$Next)
}
function IsolateGitEnvironment {
    foreach ($item in @(Get-ChildItem Env: | Where-Object { $_.Name -like 'GIT_*' })) {
        $script:restoreGitEnv[$item.Name] = $item.Value
        [Environment]::SetEnvironmentVariable($item.Name, $null, 'Process')
    }
    $forced = @{'GIT_CONFIG_NOSYSTEM'='1';'GIT_CONFIG_GLOBAL'='NUL';
        'GIT_TERMINAL_PROMPT'='0';'GIT_NO_LAZY_FETCH'='1';'GIT_LFS_SKIP_SMUDGE'='1'}
    foreach ($name in $forced.Keys) {
        if (-not $script:restoreGitEnv.ContainsKey($name)) { $script:restoreGitEnv[$name] = $null }
        [Environment]::SetEnvironmentVariable($name, $forced[$name], 'Process')
    }
}
function RestoreGitEnvironment {
    foreach ($name in $script:restoreGitEnv.Keys) {
        [Environment]::SetEnvironmentVariable($name, $script:restoreGitEnv[$name], 'Process')
    }
}
function Git([string[]]$GitArgs, [string]$OnError) {
    try {
        $argsAll = @($script:gitFlags) + @($GitArgs)
        $out = & $script:gitExe @argsAll 2>$null
        if ($LASTEXITCODE -ne 0) { Block $OnError }
        return (@($out) -join "`n").Trim()
    } catch { Block $OnError }
}
function SourceReadback {
    if (-not (Test-Path -LiteralPath $script:target -PathType Container)) { Block 'LOCAL_CLONE_NOT_PRESENT' }
    Assert-NoReparse $script:target
    $dot = Join-Path $script:target '.git'
    if (-not (Test-Path -LiteralPath $dot -PathType Container)) { Block 'SOURCE_GIT_DIR_NOT_NORMAL' }
    Assert-NoReparse $dot
    Assert-NoReparse (Join-Path $dot 'config')
    $root = Git @('-C',$script:target,'rev-parse','--show-toplevel') 'SOURCE_ROOT_FAILED'
    if ([IO.Path]::GetFullPath($root).TrimEnd('\') -ine [IO.Path]::GetFullPath($script:target).TrimEnd('\')) { Block 'SOURCE_ROOT_MISMATCH' }
    $origin = Git @('-C',$script:target,'remote','get-url','origin') 'SOURCE_ORIGIN_FAILED'
    if ($origin -notin @($script:repoUrl,'https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric',
        'git@github.com:rassvetpublic-spec/Rassvet_AI_Fabric.git')) { Block 'SOURCE_ORIGIN_WRONG' }
    $head = Git @('-C',$script:target,'rev-parse','HEAD') 'SOURCE_HEAD_FAILED'
    if ($head.ToLowerInvariant() -ne $script:pin) { Block 'SOURCE_PIN_MISMATCH' }
    $branchPin = Git @('-C',$script:target,'rev-parse','--verify',('refs/remotes/origin/' + $script:branch)) 'SOURCE_REMOTE_REF_MISSING'
    if ($branchPin.ToLowerInvariant() -ne $script:pin) { Block 'SOURCE_REMOTE_PIN_MISMATCH' }
    $status = Git @('-C',$script:target,'status','--porcelain=v1','--untracked-files=all') 'SOURCE_STATUS_FAILED'
    if (-not [string]::IsNullOrWhiteSpace($status)) { Block 'SOURCE_DIRTY' }
    $ignored = Git @('-C',$script:target,'ls-files','--others','--ignored','--exclude-standard') 'SOURCE_IGNORED_SCAN_FAILED'
    if (-not [string]::IsNullOrWhiteSpace($ignored)) { Block 'SOURCE_IGNORED_FILES' }
    # Git's assume-unchanged and skip-worktree index flags can conceal local edits.
    $fileFlags = Git @('-C',$script:target,'ls-files','-v') 'SOURCE_INDEX_FLAGS_FAILED'
    foreach ($entryLine in @($fileFlags -split "`n")) {
        if ([string]::IsNullOrWhiteSpace($entryLine)) { continue }
        if (-not $entryLine.StartsWith('H ')) { Block 'SOURCE_HIDDEN_INDEX_FLAGS' }
    }
    foreach ($entry in @(
        @{Name='src\rai_fabric\worktree_review.py';Sha=$script:codeSha},
        @{Name='tests\test_worktree_review.py';Sha=$script:testSha},
        @{Name='scripts\demo-worktree-review.ps1';Sha=$script:demoSha})) {
        $f = Join-Path $script:target $entry.Name
        Assert-NoReparse $f
        if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { Block 'EXPECTED_SOURCE_FILE_MISSING' }
        if ((Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Sha) { Block 'SOURCE_FILE_SHA256_MISMATCH' }
    }
}
function Select-Python {
    $candidates = @()
    foreach ($name in @('py.exe','python.exe')) {
        $exe = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $exe -and $exe.CommandType -eq 'Application' -and $exe.Source -notmatch '(?i)[\\/]WindowsApps[\\/]') {
            $prefix = if ($name -eq 'py.exe') { @('-3') } else { @() }
            $candidates += ,([pscustomobject]@{Exe=$exe.Source;Prefix=$prefix})
        }
    }
    $base = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $base -PathType Container) {
        foreach ($dir in @(Get-ChildItem -LiteralPath $base -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue)) {
            $exe = Join-Path $dir.FullName 'python.exe'
            if (Test-Path -LiteralPath $exe -PathType Leaf) { $candidates += ,([pscustomobject]@{Exe=$exe;Prefix=@()}) }
        }
    }
    foreach ($c in $candidates) {
        Assert-NoReparse $c.Exe
        try {
            $probeArgs = @($c.Prefix) + @('-I','-B','-c',
                'import sys; raise SystemExit(0 if sys.platform=="win32" and sys.version_info >= (3,11) else 2)')
            & $c.Exe @probeArgs 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $c }
        } catch { continue }
    }
    Block 'REAL_PYTHON_311_REQUIRED'
}
function QuoteWin([string]$Value) {
    if ($Value.Length -eq 0) { return '""' }
    if ($Value -notmatch '[\s"]') { return $Value }
    $r = '"'; $slashes = 0
    foreach ($ch in $Value.ToCharArray()) {
        if ($ch -eq '\') { $slashes++; continue }
        if ($ch -eq '"') {
            $r += ('\' * ($slashes * 2 + 1)) + '"'; $slashes = 0; continue
        }
        if ($slashes -gt 0) { $r += ('\' * $slashes); $slashes = 0 }
        $r += $ch
    }
    if ($slashes -gt 0) { $r += ('\' * ($slashes * 2)) }
    return $r + '"'
}
function RunProcess([string[]]$Arguments, [int]$MaxSeconds, [switch]$WithSrc) {
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $script:python.Exe
    $all = @($script:python.Prefix) + @($Arguments)
    $psi.Arguments = (@($all | ForEach-Object { QuoteWin ([string]$_) }) -join ' ')
    $psi.WorkingDirectory = $script:target
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = $script:utf8
    $psi.StandardErrorEncoding = $script:utf8
    foreach ($k in @('OPENAI_API_KEY','CODEX_API_KEY','CODEX_ACCESS_TOKEN','GOOGLE_API_KEY',
                     'GEMINI_API_KEY','ANTHROPIC_API_KEY','OPENAI_BASE_URL')) { $psi.EnvironmentVariables.Remove($k) }
    $psi.EnvironmentVariables['PYTHONUTF8'] = '1'
    $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $psi.EnvironmentVariables['PYTHONNOUSERSITE'] = '1'
    $psi.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'
    $psi.EnvironmentVariables['GIT_NO_LAZY_FETCH'] = '1'
    $psi.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    $psi.EnvironmentVariables['GIT_CONFIG_NOSYSTEM'] = '1'
    $psi.EnvironmentVariables['GIT_CONFIG_GLOBAL'] = 'NUL'
    $psi.EnvironmentVariables['GIT_LFS_SKIP_SMUDGE'] = '1'
    if ($WithSrc) { $psi.EnvironmentVariables['PYTHONPATH'] = Join-Path $script:target 'src' }
    else { $psi.EnvironmentVariables.Remove('PYTHONPATH') }
    $p = [Diagnostics.Process]::new()
    $p.StartInfo = $psi
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        if (-not $p.Start()) { Block 'CHILD_PROCESS_NOT_STARTED' }
        $outTask = $p.StandardOutput.ReadToEndAsync()
        $errTask = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit($MaxSeconds * 1000)) {
            try { $p.Kill() } catch {}
            [void]$p.WaitForExit(3000)
            Block 'CHILD_PROCESS_TIMEOUT'
        }
        $sw.Stop()
        # A child process can inherit pipe handles: a parent exit alone is not enough.
        if (-not $outTask.Wait(8000) -or -not $errTask.Wait(8000)) { Block 'CHILD_PIPE_DRAIN_TIMEOUT' }
        $stdout = $outTask.GetAwaiter().GetResult()
        $stderr = $errTask.GetAwaiter().GetResult()
        if ($stdout.Length -gt 131072 -or $stderr.Length -gt 131072) { Block 'CHILD_OUTPUT_TOO_LARGE' }
        return [pscustomobject]@{Exit=$p.ExitCode;Out=$stdout;Err=$stderr;ElapsedMs=$sw.ElapsedMilliseconds}
    } catch {
        $v = [string]$_.Exception.Message
        if ($v -match '^[A-Z0-9_]{1,80}$') { throw }
        Block 'CHILD_PROCESS_FAILED_REDACTED'
    } finally { $p.Dispose() }
}
function CheckTests([string]$Pattern, [int]$ExpectedExact, [string]$Stage) {
    Event 'START' $Stage 'UNITTEST_LOCAL_ONLY' $script:allowedNext
    $args = @('-B','-m','unittest','discover','-s',(Join-Path $script:target 'tests'),'-p',$Pattern,'-v')
    $res = RunProcess $args 240 -WithSrc
    $m = [regex]::Match($res.Err,'(?m)^Ran\s+(\d+)\s+tests?\s+in\s+')
    $ok = [regex]::IsMatch($res.Err,'(?m)^OK(?:\s*\([^\r\n]*\))?\s*$')
    $sk = [regex]::Match($res.Err,'(?m)\bskipped=(\d+)\b')
    $count = if ($m.Success) { [int]$m.Groups[1].Value } else { 0 }
    $skipped = if ($sk.Success) { [int]$sk.Groups[1].Value } else { 0 }
    if ($res.Exit -ne 0 -or -not $ok -or $count -lt 1) { Block 'UNITTEST_FAILURE_OR_SUMMARY_MISSING' }
    if ($ExpectedExact -gt 0 -and $count -ne $ExpectedExact) { Block 'UNITTEST_EXPECTED_COUNT_MISMATCH' }
    if ($skipped -ne 0) { Block 'UNITTEST_UNEXPECTED_SKIP' }
    $safe = [ordered]@{status='PASS';tests_run=$count;skipped=$skipped;exit_code=$res.Exit;
        elapsed_ms=$res.ElapsedMs;output_sha256=Sha256String ($res.Out + $res.Err)}
    $script:results[$Stage] = $safe
    SourceReadback
    Event 'PASS' $Stage 'TEST_COUNT_AND_SOURCE_CLEAN' $script:allowedNext
}
function CheckMock {
    Event 'START' 'OFFLINE_MOCK' 'PINNED_OWNED_CODE_ONLY' $script:allowedNext
    $output = Join-Path $env:LOCALAPPDATA 'Rassvet_AI_Fabric\worktree_review'
    Assert-NoReparse $output
    [void][IO.Directory]::CreateDirectory($output)
    $args = @('-I','-B',(Join-Path $script:target 'src\rai_fabric\worktree_review.py'),
        'demo','--repo',$script:target,'--pin',$script:pin,'--output-root',$output)
    $res = RunProcess $args 180
    if ($res.Exit -ne 0) { Block 'OFFLINE_MOCK_EXIT_NONZERO' }
    try { $doc = $res.Out.Trim() | ConvertFrom-Json } catch { Block 'OFFLINE_MOCK_NOT_JSON' }
    if ($doc.verdict -ne 'PENDING_HUMAN_APPROVAL' -or $doc.mock_tests_passed -ne 3 -or
        $doc.cursor -ne 'RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE') { Block 'OFFLINE_MOCK_VERDICT_INVALID' }
    $basename = [IO.Path]::GetFileName(([string]$doc.run_dir).TrimEnd('\'))
    if ($basename -notmatch '^RAIF_10_1_[0-9a-f]{12}$') { Block 'OFFLINE_MOCK_RUN_ID_INVALID' }
    $dir = Join-Path $output $basename
    if ([IO.Path]::GetFullPath($dir).TrimEnd('\') -ine [IO.Path]::GetFullPath($doc.run_dir).TrimEnd('\')) { Block 'OFFLINE_MOCK_PATH_UNTRUSTED' }
    Assert-NoReparse $dir
    $patch = Join-Path $dir 'REVIEW.patch'
    $check = Join-Path $dir 'CHECKPOINT.json'
    if (-not (Test-Path -LiteralPath $patch -PathType Leaf) -or
        -not (Test-Path -LiteralPath $check -PathType Leaf)) { Block 'OFFLINE_MOCK_EVIDENCE_MISSING' }
    $pHash = (Get-FileHash -LiteralPath $patch -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($pHash -ne $doc.patch_sha256) { Block 'OFFLINE_MOCK_PATCH_HASH_MISMATCH' }
    try { $cp = Get-Content -LiteralPath $check -Raw -Encoding UTF8 | ConvertFrom-Json } catch { Block 'OFFLINE_MOCK_CHECKPOINT_INVALID' }
    if ($cp.verdict -ne 'PENDING_HUMAN_APPROVAL' -or $cp.evidence.mock_tests_passed -ne 3 -or
        $cp.evidence.manual_merge_gate -ne $true) { Block 'OFFLINE_MOCK_GATE_INVALID' }
    $script:results['mock'] = [ordered]@{status='PASS_WITH_SCOPE';synthetic_tests=3;patch_sha256=$pHash;
        run_id=$basename;model_turns=0;manual_merge_gate=$true;elapsed_ms=$res.ElapsedMs}
    SourceReadback
    Event 'PASS' 'OFFLINE_MOCK' 'THREE_SYNTHETIC_TESTS_VERIFIED' $script:allowedNext
}

try {
    if (-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) { Block 'WINDOWS_ONLY' }
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { Block 'LOCALAPPDATA_MISSING' }
    $script:audit = Join-Path (Join-Path $env:LOCALAPPDATA 'Rassvet_AI_Fabric\host_qa') $script:runId
    Assert-NoReparse $script:audit
    [void][IO.Directory]::CreateDirectory($script:audit)
    $script:auditSafe = $true
    Event 'START' 'QA_PREFLIGHT' 'AUDIT_CREATED' $script:cursor
    if (-not (Test-Path -LiteralPath 'C:\GIT' -PathType Container)) { Block 'C_GIT_PARENT_MISSING' }
    $fixed = [IO.DriveInfo]::new('C:\')
    if ($fixed.DriveType -ne [IO.DriveType]::Fixed) { Block 'C_DRIVE_NOT_FIXED' }
    Assert-NoReparse $script:target
    $c = Get-Command 'git.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $c -or $c.CommandType -ne 'Application' -or $c.Source -match '(?i)[\\/]WindowsApps[\\/]') { Block 'REAL_GIT_REQUIRED' }
    $script:gitExe = $c.Source
    Assert-NoReparse $script:gitExe
    IsolateGitEnvironment
    SourceReadback
    Event 'PASS' 'CLONE_READBACK' 'PIN_SOURCE_HASHES_AND_STATUS_VERIFIED' $script:allowedNext
    $script:python = Select-Python
    Event 'PASS' 'PYTHON_PREFLIGHT' 'REAL_PYTHON_311_VERIFIED' $script:allowedNext
    if (-not $Run) {
        $script:finalVerdict = 'READY_FOR_RUN'
        $script:finalCode = 'INSPECTION_COMPLETE_TESTS_NOT_RUN'
        Checkpoint $script:finalVerdict $script:finalCode
        exit 0
    }
    CheckTests 'test_worktree_review.py' 20 'targeted'
    CheckTests 'test_*.py' 0 'full'
    CheckMock
    $script:finalVerdict = 'PASS_WITH_SCOPE'
    $script:finalCode = 'WINDOWS_LOCAL_UNITTESTS_AND_MOCK_PASS'
    $script:cursor = 'RAI-FABRIC/10.1C-ADVERSARIAL_OFFLINE_REVIEW'
    Event 'PASS' 'HOST_QA' $script:finalCode $script:cursor
    Checkpoint $script:finalVerdict $script:finalCode
    AtomicFile (Join-Path $script:audit 'SUMMARY.json') (([ordered]@{schema='RAIF_10_1B_RESULT/1';
        verdict=$script:finalVerdict;code=$script:finalCode;cursor=$script:cursor;
        expected_sha=$script:pin;result=$script:results;run_id=$script:runId} | ConvertTo-Json -Depth 8) + "`n")
    exit 0
} catch {
    $errorCode = [string]$_.Exception.Message
    if ($errorCode -notmatch '^[A-Z0-9_]{1,80}$') { $errorCode = 'HOST_QA_FAILED_REDACTED' }
    $script:finalVerdict = 'BLOCKED'
    $script:finalCode = $errorCode
    $next = if ($errorCode -like 'LOCAL_CLONE_*' -or $errorCode -like 'SOURCE_*' -or
        $errorCode -eq 'C_GIT_PARENT_MISSING') {
        'RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION'
    } else { 'RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE' }
    if ($script:auditSafe) {
        try { Event 'BLOCKED' 'HOST_QA' $errorCode $next; Checkpoint 'BLOCKED' $errorCode }
        catch { Write-Host '[BLOCKED] AUDIT_WRITE_FAILED' }
    }
    Write-Host ('[BLOCKED] {0}; source clone is not intentionally modified.' -f $errorCode)
    exit 2
} finally {
    RestoreGitEnvironment
}
