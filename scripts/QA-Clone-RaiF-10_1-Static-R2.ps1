#requires -Version 5.1
<#
Статическая проверка запускатора 10.1A R2 штатным парсером Windows PowerShell.
Ничего не клонирует, не читает учётные записи, не выполняет тесты/модели.
Результат PASS_STATIC_ONLY не является подтверждением Windows clone.
#>
[CmdletBinding()]
param(
    [string]$ScriptPath = (Join-Path $PSScriptRoot 'Clone-RaiF-10_1-Safe-R2.ps1')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$expectedPin = 'a0daf08375b70d202b3dc7b5ab51f894e87d9ae0'
$scriptName = 'Clone-RaiF-10_1-Safe-R2.ps1'
$testsPassed = 0
try {
    if (-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) {
        throw 'WINDOWS_ONLY'
    }
    if ([IO.Path]::GetFileName($ScriptPath) -cne $scriptName) { throw 'SCRIPT_NAME_NOT_EXPECTED' }
    $path = [IO.Path]::GetFullPath($ScriptPath)
    if (-not [IO.File]::Exists($path)) { throw 'SCRIPT_NOT_FOUND' }
    $rawBytes = [IO.File]::ReadAllBytes($path)
    if ($rawBytes.Length -lt 3 -or $rawBytes[0] -ne 239 -or
        $rawBytes[1] -ne 187 -or $rawBytes[2] -ne 191) { throw 'UTF8_BOM_REQUIRED' }
    $text = [Text.Encoding]::UTF8.GetString($rawBytes, 3, $rawBytes.Length - 3)
    $testsPassed += 1
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if ($null -eq $ast -or ($null -ne $errors -and $errors.Count -gt 0)) { throw 'POWERSHELL_SYNTAX_FAILED' }
    $testsPassed += 1
    foreach ($needle in @(
        $expectedPin, 'EXISTING_IGNORED_CONTENT_PRESENT', 'REMOTE_BRANCH_MOVED',
        'TREE_CASE_COLLISION', 'CHECKOUT_ATTR_OR_SUBMODULE_BLOCKED',
        'EXISTING_TARGET_RECONCILIATION', 'Append-SecureEvent',
        'staging_still_exists', 'File]::Replace', 'Assert-NoReparse',
        'GIT_TERMINAL_PROMPT', 'RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE')) {
        if (-not $text.Contains($needle)) { throw 'GUARD_NOT_FOUND' }
        $testsPassed += 1
    }
    if ($text.Contains('[IO.File]::AppendAllText(')) { throw 'LEGACY_UNSYNCED_JOURNAL' }
    $testsPassed += 1
    if ($text.Contains('audit_dir = $script:audit')) { throw 'UNREDACTED_AUDIT_PATH' }
    $testsPassed += 1
    $safe = [ordered]@{status='PASS_STATIC_ONLY'; parser='WindowsPowerShell5.1';
        assertions_passed=$testsPassed; pin=$expectedPin;
        sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant();
        clone_performed=$false; ci_runs=0; model_turns=0;
        cursor='RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION'}
    $safe | ConvertTo-Json -Compress -Depth 4
    exit 0
} catch {
    $errorCode = [string]$_.Exception.Message
    if ($errorCode -notmatch '^[A-Z0-9_]{1,80}$') { $errorCode = 'STATIC_QA_FAILED_REDACTED' }
    [ordered]@{status='BLOCKED';code=$errorCode;assertions_passed=$testsPassed;
        clone_performed=$false;ci_runs=0;model_turns=0;
        cursor='RAI-FABRIC/10.1A-CLONE_SCRIPT_HARDENING'} |
        ConvertTo-Json -Compress -Depth 4
    exit 2
}
