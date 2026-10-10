#requires -Version 5.1
<#
RAiF 10.1A R2: безопасный clone/check existing directory на Windows.
По умолчанию — только инспекция. Реальный clone — параметр -Apply.
При наличии целевого каталога ничего не удаляется, не переименовывается,
не перезаписывается и не выполняется fetch/checkout существующего клона.
Выходные сведения без токенов/сырых stdout/stderr: JSONL, CURSOR.json, CHECKPOINT.json.
НЕ запускает Codex, Antigravity, CI, push, merge, тесты и модели.
#>
[CmdletBinding()]
param([switch]$Apply)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:repoUrl = 'https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric.git'
$script:branch = 'raif-10-1-worktree-offline-20261010'
$script:pinSha = 'a0daf08375b70d202b3dc7b5ab51f894e87d9ae0'
$script:target = 'C:\GIT\Rassvet_AI_Fabric'
$script:parent = 'C:\GIT'
$script:cursor = 'RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION'
$script:runId = 'RAIF_CLONE_10_1_' + ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')) + '_' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
$script:audit = Join-Path (Join-Path $env:LOCALAPPDATA 'Rassvet_AI_Fabric\clone_audit') $script:runId
$script:utf8 = [System.Text.UTF8Encoding]::new($false)
$script:gitExe = $null
$script:gitFlags = @()
$script:stage = $null
$script:mode = if ($Apply) { 'APPLY' } else { 'INSPECT_ONLY' }
$script:restoreEnv = @{}
$script:mutations = 0
$script:finalVerdict = 'BLOCKED'
$script:finalCode = 'NOT_STARTED'
$script:actualHead = $null
$script:lastStage = 'NOT_STARTED'
$script:gitSha256 = $null
$script:auditSafe = $false
$script:stageAttempted = $false
$script:treeCount = $null
$script:remoteVerified = $false
$script:action = 'NOT_STARTED'

function Assert-NoReparse([string]$PathValue) {
    $candidate = [IO.Path]::GetFullPath($PathValue)
    while ($true) {
        if (Test-Path -LiteralPath $candidate) {
            $attributes = [IO.File]::GetAttributes($candidate)
            if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'REPARSE_PATH_BLOCKED'
            }
        }
        $ancestor = [IO.Path]::GetDirectoryName($candidate.TrimEnd('\'))
        if ([string]::IsNullOrWhiteSpace($ancestor) -or $ancestor -eq $candidate) { break }
        $candidate = $ancestor
    }
}

function Get-SHA256String([string]$Value) {
    $bytes = $script:utf8.GetBytes($Value)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Write-SecureText([string]$Path, [string]$Value) {
    # Запись checkpoint/cursor: только новый файл или атомарная замена в том же каталоге.
    Assert-NoReparse $Path
    $directory = [IO.Path]::GetDirectoryName($Path)
    $temporary = Join-Path $directory ('.' + [IO.Path]::GetFileName($Path) + '.' +
        [Guid]::NewGuid().ToString('N') + '.tmp')
    $bytes = $script:utf8.GetBytes($Value)
    try {
        $stream = [IO.FileStream]::new($temporary, [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write, [IO.FileShare]::None, 4096, [IO.FileOptions]::WriteThrough)
        try {
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        } finally { $stream.Dispose() }
        Assert-NoReparse $Path
        if ([IO.File]::Exists($Path)) {
            [IO.File]::Replace($temporary, $Path, $null)
        } else {
            [IO.File]::Move($temporary, $Path)
        }
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    }
}

function Append-SecureEvent([string]$EventJson) {
    $path = Join-Path $script:audit 'STAGES.jsonl'
    Assert-NoReparse $path
    $bytes = $script:utf8.GetBytes($EventJson)
    $stream = [IO.FileStream]::new($path, [IO.FileMode]::Append,
        [IO.FileAccess]::Write, [IO.FileShare]::Read, 4096, [IO.FileOptions]::WriteThrough)
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally { $stream.Dispose() }
}

function Save-Cursor([string]$Status, [string]$Stage, [string]$Code, [string]$Next) {
    Assert-NoReparse $script:audit
    foreach ($field in @($Status, $Stage, $Code)) {
        if ($field -notmatch '^[A-Z0-9_\-]{1,80}$') { throw 'LOG_ENUM_INVALID' }
    }
    if ($Next -notmatch '^RAI-FABRIC/[A-Z0-9_.\-]+$') { throw 'CURSOR_FORMAT_INVALID' }
    $script:cursor = $Next
    $script:lastStage = $Stage
    $event = [ordered]@{
        utc = [DateTime]::UtcNow.ToString('o')
        run_id = $script:runId
        stage = $Stage
        verdict = $Status
        code = $Code
        cursor = $Next
    }
    $eventJson = ($event | ConvertTo-Json -Compress -Depth 5) + "`n"
    Append-SecureEvent $eventJson
    $cursorDoc = [ordered]@{schema='RAIF_CURSOR/1'; utc=$event.utc; run_id=$script:runId;
        stage=$Stage; verdict=$Status; cursor=$Next; code=$Code}
    Write-SecureText (Join-Path $script:audit 'CURSOR.json') (($cursorDoc | ConvertTo-Json -Depth 5) + "`n")
    Save-Checkpoint 'PARTIAL' $Code
    Write-Host ('[{0}] {1} : {2} -> {3}' -f $Status, $Stage, $Code, $Next)
}

function Save-Checkpoint([string]$Verdict, [string]$Code) {
    Assert-NoReparse $script:audit
    $stageName = $null
    $stageExists = $false
    if ($null -ne $script:stage) {
        $stageName = [IO.Path]::GetFileName($script:stage)
        $stageExists = Test-Path -LiteralPath $script:stage
    }
    $doc = [ordered]@{
        schema = 'RAI_FABRIC_CLONE_CHECKPOINT/2'
        utc = [DateTime]::UtcNow.ToString('o')
        run_id = $script:runId
        stage = 'RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION'
        last_stage = $script:lastStage
        verdict = $Verdict
        code = $Code
        cursor = $script:cursor
        repository = 'rassvetpublic-spec/Rassvet_AI_Fabric'
        expected_branch = $script:branch
        expected_head = $script:pinSha
        git_binary_sha256 = $script:gitSha256
        observed_head = $script:actualHead
        target = $script:target
        action = $script:action
        mode = $script:mode
        existing_target_mutations = 0
        new_clone_mutations = $script:mutations
        model_turns = 0
        github_actions_requested = 0
        push_count = 0
        merge_count = 0
        host_os = 'Windows'
        audit_dir = ('%LOCALAPPDATA%\Rassvet_AI_Fabric\clone_audit\' + $script:runId)
        staging_basename = $stageName
        staging_attempted = $script:stageAttempted
        staging_still_exists = $stageExists
        tree_entry_count = $script:treeCount
        remote_pin_verified_at_promotion = $script:remoteVerified
        note = 'PASS означает только локальный clone/readback, не Windows QA и не разрешение merge. Отказ не удаляет staging.'
    }
    $canonical = ($doc | ConvertTo-Json -Compress -Depth 6)
    $doc['sha256'] = Get-SHA256String $canonical
    Write-SecureText (Join-Path $script:audit 'CHECKPOINT.json') (($doc | ConvertTo-Json -Depth 6) + "`n")
}

function Assert-WindowsLocalPaths {
    if (-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) {
        throw 'WINDOWS_ONLY'
    }
    if (-not (Test-Path -LiteralPath $script:parent -PathType Container)) { throw 'C_GIT_PARENT_MISSING' }
    $drive = [IO.DriveInfo]::new('C:\')
    if ($drive.DriveType -ne [IO.DriveType]::Fixed) { throw 'C_DRIVE_NOT_FIXED' }
    Assert-NoReparse $script:parent
    Assert-NoReparse $script:target
    Assert-NoReparse $script:audit
}

function Set-IsolatedGitEnvironment {
    # git.exe может читать GIT_CONFIG_COUNT/GIT_DIR/GIT_WORK_TREE из окружения:
    # такие значения запрещено наследовать при диагностике и clone.
    foreach ($variable in @(Get-ChildItem Env: | Where-Object {$_.Name -like 'GIT_*'})) {
        $script:restoreEnv[$variable.Name] = $variable.Value
        [Environment]::SetEnvironmentVariable($variable.Name, $null, 'Process')
    }
    $isolated = @{
        'GIT_CONFIG_NOSYSTEM' = '1'
        'GIT_CONFIG_GLOBAL' = 'NUL'
        'GIT_TERMINAL_PROMPT' = '0'
        'GIT_NO_LAZY_FETCH' = '1'
        'GIT_LFS_SKIP_SMUDGE' = '1'
        'GCM_INTERACTIVE' = 'never'
    }
    foreach ($key in $isolated.Keys) {
        if (-not $script:restoreEnv.ContainsKey($key)) { $script:restoreEnv[$key] = $null }
        [Environment]::SetEnvironmentVariable($key, $isolated[$key], 'Process')
    }
}

function Restore-GitEnvironment {
    foreach ($key in $script:restoreEnv.Keys) {
        [Environment]::SetEnvironmentVariable($key, $script:restoreEnv[$key], 'Process')
    }
}

function Invoke-Git([string[]]$Arguments, [string]$ErrorCode) {
    $all = @($script:gitFlags) + @($Arguments)
    try {
        $lines = & $script:gitExe @all 2>$null
        if ($LASTEXITCODE -ne 0) { throw $ErrorCode }
        if ($null -eq $lines) { return '' }
        return ((@($lines) -join "`n").Trim())
    } catch {
        throw $ErrorCode
    }
}

function Assert-Source([string]$Folder) {
    $gitDir = Join-Path $Folder '.git'
    if (-not (Test-Path -LiteralPath $gitDir -PathType Container)) { throw 'EXISTING_NOT_A_NORMAL_GIT_CLONE' }
    Assert-NoReparse $Folder
    Assert-NoReparse $gitDir
    Assert-NoReparse (Join-Path $gitDir 'config')
    $root = Invoke-Git -Arguments @('-C', $Folder, 'rev-parse', '--show-toplevel') -ErrorCode 'EXISTING_GIT_ROOT_INVALID'
    if ([IO.Path]::GetFullPath($root).TrimEnd('\') -ine [IO.Path]::GetFullPath($Folder).TrimEnd('\')) {
        throw 'EXISTING_GIT_ROOT_MISMATCH'
    }
    $remote = Invoke-Git -Arguments @('-C', $Folder, 'remote', 'get-url', 'origin') -ErrorCode 'ORIGIN_MISSING'
    $allowedOrigins = @($script:repoUrl, 'git@github.com:rassvetpublic-spec/Rassvet_AI_Fabric.git',
        'https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric')
    if ($remote -notin $allowedOrigins) { throw 'ORIGIN_NOT_EXPECTED' }
    $dirty = Invoke-Git -Arguments @('-C', $Folder, 'status', '--porcelain=v1', '--untracked-files=all') -ErrorCode 'STATUS_FAILED'
    if (-not [string]::IsNullOrWhiteSpace($dirty)) { throw 'EXISTING_WORKTREE_DIRTY' }
    # Обычный status не сообщает о файлах под .gitignore. Их наличие не разрешает PASS.
    $ignored = Invoke-Git -Arguments @('-C', $Folder, 'ls-files', '--others', '--ignored', '--exclude-standard') -ErrorCode 'IGNORED_CHECK_FAILED'
    if (-not [string]::IsNullOrWhiteSpace($ignored)) { throw 'EXISTING_IGNORED_CONTENT_PRESENT' }
    $head = Invoke-Git -Arguments @('-C', $Folder, 'rev-parse', 'HEAD') -ErrorCode 'HEAD_READ_FAILED'
    $script:actualHead = $head.ToLowerInvariant()
    if ($script:actualHead -ne $script:pinSha) { throw 'EXISTING_HEAD_DIFFERENT' }
    $remoteBranch = Invoke-Git -Arguments @('-C', $Folder, 'rev-parse', '--verify', ('refs/remotes/origin/' + $script:branch)) -ErrorCode 'REMOTE_BRANCH_MISSING'
    if ($remoteBranch.ToLowerInvariant() -ne $script:pinSha) { throw 'EXISTING_BRANCH_PIN_DIFFERENT' }
    return $true
}

try {
    # Аудит намеренно записывается вне целевого клона. Новый уникальный каталог;
    # ни один существующий лог другого run не перезаписывается.
    if (-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) { throw 'WINDOWS_ONLY' }
    Assert-NoReparse $script:audit
    [IO.Directory]::CreateDirectory($script:audit) | Out-Null
    $script:auditSafe = $true
    Save-Cursor 'START' 'PREFLIGHT' 'RUN_INITIALIZED' $script:cursor
    Assert-WindowsLocalPaths
    Save-Cursor 'PASS' 'PREFLIGHT' 'LOCAL_PATHS_VERIFIED' $script:cursor

    $command = Get-Command 'git.exe' -ErrorAction SilentlyContinue
    if ($null -eq $command -or $command.CommandType -ne 'Application' -or
        $command.Source -match '(?i)[\\/]WindowsApps[\\/]') { throw 'REAL_GIT_EXE_REQUIRED' }
    $script:gitExe = $command.Source
    Assert-NoReparse $script:gitExe
    $script:gitSha256 = (Get-FileHash -LiteralPath $script:gitExe -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:gitFlags = @('-c', 'credential.helper=', '-c', 'core.fsmonitor=false',
        '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', '-c', 'core.safecrlf=true',
        '-c', 'core.sparseCheckout=false', '-c', 'filter.lfs.required=false',
        '-c', 'filter.lfs.smudge=', '-c', 'submodule.recurse=false',
        '-c', 'protocol.file.allow=never', '-c', 'protocol.ext.allow=never')
    Set-IsolatedGitEnvironment
    $version = Invoke-Git -Arguments @('--version') -ErrorCode 'GIT_VERSION_UNAVAILABLE'
    if ($version -notmatch '^git version [0-9]') { throw 'GIT_VERSION_UNRECOGNIZED' }
    Save-Cursor 'PASS' 'TOOLS' 'GIT_LOCAL_READBACK_OK' $script:cursor

    if (Test-Path -LiteralPath $script:target) {
        $script:action = 'EXISTING_INSPECT_ONLY'
        Save-Cursor 'START' 'EXISTING_TARGET' 'NO_MUTATIONS_ALLOWED' $script:cursor
        Assert-Source $script:target | Out-Null
        Save-Cursor 'PASS' 'EXISTING_TARGET' 'EXACT_REPOSITORY_PIN_CLEAN' 'RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE'
        $script:finalVerdict = 'PASS_WITH_SCOPE'
        $script:finalCode = 'EXISTING_CLONE_VERIFIED_NO_NEW_CLONE'
        Save-Checkpoint $script:finalVerdict $script:finalCode
        exit 0
    }

    Save-Cursor 'PASS' 'EMPTY_TARGET' 'TARGET_ABSENT_SAFE_TO_CLONE' $script:cursor
    if (-not $Apply) {
        $script:action = 'INSPECT_ONLY_NO_CLONE'
        $script:finalVerdict = 'READY_FOR_APPLY'
        $script:finalCode = 'NO_CLONE_EXECUTED'
        Save-Checkpoint $script:finalVerdict $script:finalCode
        exit 0
    }

    $script:action = 'CLONE_STAGING'
    $script:stage = Join-Path $script:parent ('.RAIF_CLONE_STAGE_' + [Guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $script:stage) { throw 'STAGING_PATH_OCCUPIED' }
    $hooks = Join-Path $script:audit 'empty_hooks'
    [IO.Directory]::CreateDirectory($hooks) | Out-Null
    $script:gitFlags += @('-c', ('core.hooksPath=' + $hooks))
    Save-Cursor 'START' 'CLONE' 'REMOTE_BRANCH_SHA_PIN_REQUIRED' $script:cursor
    $script:stageAttempted = $true
    $script:mutations = 1 # Попытка создания нового staging, даже если clone аварийно завершится.
    $silent = Invoke-Git -Arguments @('clone', '--quiet', '--no-checkout', '--no-tags', '--single-branch',
        '--branch', $script:branch, $script:repoUrl, $script:stage) -ErrorCode 'CLONE_FAILED'
    $remotePin = Invoke-Git -Arguments @('-C', $script:stage, 'rev-parse', '--verify', ('refs/remotes/origin/' + $script:branch)) -ErrorCode 'CLONED_REF_MISSING'
    if ($remotePin.ToLowerInvariant() -ne $script:pinSha) { throw 'REMOTE_HEAD_NOT_PINNED' }
    # Режимы объекта и имена проверяем ДО checkout: запрет symlink, gitlink,
    # атрибутов фильтров, неканонических Windows имён и case-fold коллизий.
    $treeFiles = Invoke-Git -Arguments @('-C', $script:stage, 'ls-tree', '-r', '--full-tree',
        $script:pinSha) -ErrorCode 'TREE_INSPECTION_FAILED'
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $script:treeCount = 0
    foreach ($line in @($treeFiles -split "`n")) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $script:treeCount += 1
        if ($script:treeCount -gt 3000) { throw 'TREE_FILE_LIMIT_EXCEEDED' }
        if ($line -match '^(100644|100755) blob [0-9a-f]{40}\t(.+)$') {
            $rel = $Matches[2]
        } else {
            throw 'TREE_UNSUPPORTED_ENTRY_OR_ESCAPED_PATH'
        }
        if ($rel.StartsWith('"') -or $rel.Contains('\') -or $rel.StartsWith('/') -or
            $rel.Length -gt 230) { throw 'TREE_UNSAFE_PATH' }
        if (-not $seen.Add($rel)) { throw 'TREE_CASE_COLLISION' }
        foreach ($part in $rel.Split('/')) {
            if ($part -eq '' -or $part -eq '.' -or $part -eq '..' -or
                $part -match '[\x00-\x1F:*?"<>|]' -or $part.EndsWith('.') -or $part.EndsWith(' ') -or
                $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
                throw 'TREE_UNSAFE_WINDOWS_NAME'
            }
        }
        if ($rel -match '(^|/)(\.gitattributes|\.gitmodules)$') {
            throw 'CHECKOUT_ATTR_OR_SUBMODULE_BLOCKED'
        }
    }
    if ($script:treeCount -eq 0) { throw 'TREE_EMPTY' }
    Save-Cursor 'PASS' 'CLONE' 'REMOTE_BRANCH_PIN_VERIFIED' $script:cursor

    $script:action = 'DETACHED_CHECKOUT'
    $checkout = Invoke-Git -Arguments @('-C', $script:stage, 'checkout', '--quiet', '--detach', $script:pinSha) -ErrorCode 'DETACHED_CHECKOUT_FAILED'
    $localHead = Invoke-Git -Arguments @('-C', $script:stage, 'rev-parse', 'HEAD') -ErrorCode 'LOCAL_HEAD_UNREADABLE'
    if ($localHead.ToLowerInvariant() -ne $script:pinSha) { throw 'LOCAL_PIN_MISMATCH' }
    $dirtyAfter = Invoke-Git -Arguments @('-C', $script:stage, 'status', '--porcelain=v1', '--untracked-files=all') -ErrorCode 'CLONED_STATUS_FAILED'
    if (-not [string]::IsNullOrWhiteSpace($dirtyAfter)) { throw 'CLONED_TREE_NOT_CLEAN' }
    $ignoredAfter = Invoke-Git -Arguments @('-C', $script:stage, 'ls-files', '--others',
        '--ignored', '--exclude-standard') -ErrorCode 'CLONED_IGNORED_CHECK_FAILED'
    if (-not [string]::IsNullOrWhiteSpace($ignoredAfter)) { throw 'CLONED_IGNORED_CONTENT_PRESENT' }
    Save-Cursor 'PASS' 'DETACHED_CHECKOUT' 'LOCAL_SHA_AND_STATUS_VERIFIED' $script:cursor

    # Второе чтение branch-head из origin: отказываем при обнаруженном drift после clone.
    # Это НЕ доказывает отсутствие TOCTOU после последнего readback.
    $liveLine = Invoke-Git -Arguments @('-C', $script:stage, 'ls-remote', '--exit-code',
        '--heads', 'origin', $script:branch) -ErrorCode 'REMOTE_LIVE_READBACK_FAILED'
    $expectedLive = '^([0-9a-fA-F]{40})\s+refs/heads/' + [Regex]::Escape($script:branch) + '$'
    if ($liveLine -match $expectedLive) {
        $remoteCurrent = $Matches[1].ToLowerInvariant()
    } else {
        throw 'REMOTE_LIVE_FORMAT_INVALID'
    }
    if ($remoteCurrent -ne $script:pinSha) { throw 'REMOTE_BRANCH_MOVED' }
    $script:remoteVerified = $true
    Save-Cursor 'PASS' 'LIVE_BRANCH_READBACK' 'REMOTE_STILL_PINNED' $script:cursor
    if (Test-Path -LiteralPath $script:target) { throw 'TARGET_CREATED_DURING_CLONE' }
    Assert-NoReparse $script:stage
    [IO.Directory]::Move($script:stage, $script:target)
    $script:action = 'NEW_CLONE_PROMOTED'
    $script:stage = $null
    $script:mutations = 2
    Assert-Source $script:target | Out-Null
    Save-Cursor 'PASS' 'CLONE_READBACK' 'TARGET_SHA_PIN_CLEAN' 'RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE'
    $script:finalVerdict = 'PASS_WITH_SCOPE'
    $script:finalCode = 'CLONE_COMPLETE_WINDOWS_QA_PENDING'
    Save-Checkpoint $script:finalVerdict $script:finalCode
    exit 0
}
catch {
    # Исключение отображаем исключительно как контролируемый код, не выводим raw exception.
    $reason = [string]$_.Exception.Message
    if ($reason -notmatch '^[A-Z0-9_\-]{1,80}$') { $reason = 'UNEXPECTED_ERROR_REDACTED' }
    $script:finalVerdict = 'BLOCKED'
    $script:finalCode = $reason
    $script:cursor = if ($reason -like 'EXISTING_*' -or $reason -eq 'ORIGIN_NOT_EXPECTED' -or
        $reason -eq 'IGNORED_CHECK_FAILED') {
        'RAI-FABRIC/10.1A-EXISTING_TARGET_RECONCILIATION'
    } else { 'RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION' }
    if ($script:auditSafe -and (Test-Path -LiteralPath $script:audit -PathType Container)) {
        try {
            Save-Cursor 'BLOCKED' 'CLONE_GATE' $reason $script:cursor
            Save-Checkpoint 'BLOCKED' $reason
        } catch { Write-Host '[BLOCKED] AUDIT_WRITE_FAILED' }
    }
    Write-Host ('[BLOCKED] {0}. Existing files are untouched. Stage, if any, is preserved.' -f $reason)
    exit 2
}
finally {
    Restore-GitEnvironment
}
