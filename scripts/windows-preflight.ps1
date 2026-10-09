# Проверка доступности компонентов Windows. Не читает профили, cookie и токены; не запускает модели.
[CmdletBinding()]
param(
    [switch]$RequireWindows
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$onWindows = ($env:OS -eq 'Windows_NT')
$requiredFiles = @('pyproject.toml', 'src/rai_fabric/cli.py', 'scripts/run-tests.ps1', 'scripts/demo.ps1')
$filesPresent = $true
foreach ($relative in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $relative) -PathType Leaf)) {
        $filesPresent = $false
    }
}

# Только обнаружение исполняемых файлов; codex/agy НЕ запускаются даже с --help.
$tools = [ordered]@{}
foreach ($name in @('python', 'py', 'git', 'codex', 'agy', 'nvidia-smi')) {
    $found = Get-Command -Name $name -ErrorAction SilentlyContinue | Select-Object -First 1
    $tools[$name] = [bool]$found
}

$pythonVersion = $null
if ($tools['python']) {
    $pythonVersion = (& python --version 2>&1 | Out-String).Trim()
} elseif ($tools['py'] -and $onWindows) {
    $pythonVersion = (& py -3 --version 2>&1 | Out-String).Trim()
}
$pythonIsSupported = $false
if ($pythonVersion -match 'Python\s+(\d+)\.(\d+)') {
    $majorVersion = [int]$Matches[1]
    $minorVersion = [int]$Matches[2]
    $pythonIsSupported = $majorVersion -gt 3 -or ($majorVersion -eq 3 -and $minorVersion -ge 11)
}

$verdict = if ($filesPresent -and $pythonIsSupported -and (-not $RequireWindows -or $onWindows)) { 'PASS' } else { 'PARTIAL' }
$report = [ordered]@{
    schema = 'RAI_FABRIC_WINDOWS_PREFLIGHT/1'
    verdict = $verdict
    system = [ordered]@{
        windows = $onWindows
        os_description = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
        architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    }
    project = [ordered]@{
        files_present = $filesPresent
        language = 'ru-RU'
    }
    runtime = [ordered]@{
        python_version = $pythonVersion
        python_supported = $pythonIsSupported
        detected_commands = $tools
    }
    subscription = [ordered]@{
        codex_app_server = 'NOT_TESTED'
        chatgpt_plan = 'NOT_TESTED'
        antigravity_auth = 'NOT_TESTED'
        oauth_tokens_read = $false
        inference_requests = 0
        api_billing_requests = 0
    }
    boundaries = [ordered]@{
        protected_profiles_read = $false
        protected_profiles_modified = $false
        bpr40_modified = $false
        sqlite_database_created = $false
    }
    cursor = 'RAI-FABRIC/09-CODEX_APP_SERVER_OFFLINE_PROTOCOL'
}
$report | ConvertTo-Json -Depth 10
if ($verdict -ne 'PASS') {
    Write-Error 'Предварительная проверка не прошла. Разрешённые компоненты отсутствуют либо платформа не подходит.' -ErrorAction Continue
    exit 2
}
