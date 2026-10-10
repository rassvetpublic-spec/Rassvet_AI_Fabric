#requires -Version 5.1
<# Pure Windows PowerShell parse and literal-contract inspection. No Git, models or filesystem writes. #>
[CmdletBinding()]
param([string]$ScriptPath = (Join-Path $PSScriptRoot 'Verify-RaiF-10_1B-Windows.ps1'))
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$passed = 0
try {
    if (-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) { throw 'WINDOWS_ONLY' }
    if ([IO.Path]::GetFileName($ScriptPath) -cne 'Verify-RaiF-10_1B-Windows.ps1') { throw 'UNEXPECTED_SCRIPT_NAME' }
    $full = [IO.Path]::GetFullPath($ScriptPath)
    if (-not [IO.File]::Exists($full)) { throw 'SCRIPT_MISSING' }
    $bytes = [IO.File]::ReadAllBytes($full)
    if ($bytes.Length -lt 3 -or $bytes[0] -ne 239 -or $bytes[1] -ne 187 -or $bytes[2] -ne 191) { throw 'UTF8_BOM_REQUIRED' }
    $passed++
    $tokens = $null; $errors = $null
    $tree = [System.Management.Automation.Language.Parser]::ParseFile($full,[ref]$tokens,[ref]$errors)
    if ($null -eq $tree -or $errors.Count -ne 0) { throw 'POWERSHELL_AST_FAILED' }
    $passed++
    $text = [Text.Encoding]::UTF8.GetString($bytes,3,$bytes.Length-3)
    foreach ($item in @(
        'a0daf08375b70d202b3dc7b5ab51f894e87d9ae0',
        'RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE',
        'RAI-FABRIC/10.1C-ADVERSARIAL_OFFLINE_REVIEW',
        'test_worktree_review.py', 'test_*.py',
        'Get-FileHash', 'SOURCE_IGNORED_FILES', 'SOURCE_HIDDEN_INDEX_FLAGS',
        'SOURCE_PIN_MISMATCH', 'SOURCE_FILE_SHA256_MISMATCH',
        'SOURCE_ORIGIN_WRONG', 'CHILD_PROCESS_TIMEOUT', 'CHILD_PIPE_DRAIN_TIMEOUT',
        'OFFLINE_MOCK_PATCH_HASH_MISMATCH', 'mock_tests_passed',
        'IsolateGitEnvironment', 'RestoreGitEnvironment',
        'Checkpoint', 'AtomicFile', 'STAGES.jsonl', 'CURSOR.json', 'SUMMARY.json',
        'PYTHONUTF8', 'PYTHONNOUSERSITE', 'PYTHONDONTWRITEBYTECODE',
        'OPENAI_API_KEY', 'GEMINI_API_KEY', 'model_turns=0', 'github_actions=0')) {
        if (-not $text.Contains($item)) { throw 'REQUIRED_CONTRACT_MARKER_MISSING' }
        $passed++
    }
    $bad = @('git push ', 'git merge ', 'git reset --hard', 'Invoke-RestMethod ',
             'Invoke-WebRequest ', 'Start-Transcript ', 'ONE_TURN_10_0_CONSUMED.json')
    foreach ($item in $bad) {
        if ($text.Contains($item)) { throw 'DANGEROUS_OPERATION_MARKER' }
        $passed++
    }
    [ordered]@{schema='RAI_FABRIC_HOST_QA_STATIC/1';verdict='PASS_STATIC_ONLY';
        checks_passed=$passed;sha256=(Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant();
        windows_tests_run=0;local_clone_performed=$false;model_turns=0;ci_runs=0;
        cursor='RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION'} | ConvertTo-Json -Compress
    exit 0
} catch {
    $code = [string]$_.Exception.Message
    if ($code -notmatch '^[A-Z0-9_]{1,80}$') { $code = 'STATIC_QA_FAILED_REDACTED' }
    [ordered]@{schema='RAI_FABRIC_HOST_QA_STATIC/1';verdict='BLOCKED';
        code=$code;checks_passed=$passed;windows_tests_run=0;model_turns=0;ci_runs=0;
        cursor='RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION'} | ConvertTo-Json -Compress
    exit 2
}
