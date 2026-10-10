# Rassvet AI Fabric: только метаданные установленного ПО, без авторизации и вызовов моделей.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Sanitize-LocalPath {
    param([AllowEmptyString()][string] $Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return '' }
    $prefixes = @(
        @{ Root = $env:LOCALAPPDATA; Label = '%LOCALAPPDATA%' },
        @{ Root = $env:APPDATA; Label = '%APPDATA%' },
        @{ Root = $env:USERPROFILE; Label = '%USERPROFILE%' },
        @{ Root = $env:ProgramFiles; Label = '%PROGRAMFILES%' },
        @{ Root = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)', 'Process'); Label = '%PROGRAMFILES(X86)%' }
    ) | Sort-Object { if ($_.Root) { $_.Root.Length } else { 0 } } -Descending
    foreach ($prefix in $prefixes) {
        if (-not [string]::IsNullOrWhiteSpace($prefix.Root) -and
            $Path.StartsWith($prefix.Root, [StringComparison]::OrdinalIgnoreCase)) {
            return $prefix.Label + $Path.Substring($prefix.Root.Length)
        }
    }
    return $Path
}

$cmdResults = [ordered]@{}
foreach ($name in @('codex', 'codex.exe', 'agy', 'agy.exe', 'git', 'git.exe', 'chrome.exe', 'ollama', 'nvidia-smi.exe')) {
    $items = @()
    try {
        $hits = @(Get-Command -Name $name -All -ErrorAction SilentlyContinue | Select-Object -First 5)
        foreach ($hit in $hits) {
            $location = ''
            if ($hit.PSObject.Properties['Source']) { $location = [string]$hit.Source }
            if (-not $location -and $hit.PSObject.Properties['Path']) { $location = [string]$hit.Path }
            $items += [ordered]@{ type = [string]$hit.CommandType; path = (Sanitize-LocalPath $location) }
        }
    } catch { }
    $cmdResults[$name] = $items
}

# Функции PowerShell имеют собственную область: для кандидатов используем список в script scope.
$script:knownPaths = New-Object 'System.Collections.Generic.List[object]'
function Add-KnownPath {
    param([string]$Product,[string]$Root,[string]$Relative)
    if ([string]::IsNullOrWhiteSpace($Root)) { return }
    $full = Join-Path $Root $Relative
    if (Test-Path -LiteralPath $full -PathType Leaf) {
        $script:knownPaths.Add([ordered]@{ product=$Product; path=(Sanitize-LocalPath $full) })
    }
}
$pf86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)','Process')
Add-KnownPath 'Git' $env:ProgramFiles 'Git\cmd\git.exe'
Add-KnownPath 'Git' $env:ProgramFiles 'Git\bin\git.exe'
Add-KnownPath 'Git' $pf86 'Git\cmd\git.exe'
Add-KnownPath 'Codex' $env:LOCALAPPDATA 'Programs\Codex\Codex.exe'
Add-KnownPath 'Codex' $env:LOCALAPPDATA 'Programs\Codex\codex.exe'
Add-KnownPath 'Codex CLI' $env:APPDATA 'npm\codex.cmd'
Add-KnownPath 'Codex CLI' $env:APPDATA 'npm\codex.ps1'
Add-KnownPath 'Antigravity' $env:LOCALAPPDATA 'Programs\Antigravity\Antigravity.exe'
Add-KnownPath 'Antigravity' $env:LOCALAPPDATA 'Programs\Google Antigravity\Antigravity.exe'
Add-KnownPath 'Antigravity CLI' $env:APPDATA 'npm\agy.cmd'
Add-KnownPath 'Antigravity CLI' $env:APPDATA 'npm\agy.ps1'
Add-KnownPath 'Chrome' $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'
Add-KnownPath 'Chrome' $pf86 'Google\Chrome\Application\chrome.exe'
Add-KnownPath 'Chrome' $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'
Add-KnownPath 'Ollama' $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
Add-KnownPath 'Ollama' $env:ProgramFiles 'Ollama\ollama.exe'

$appx = @()
if (Get-Command -Name Get-AppxPackage -ErrorAction SilentlyContinue) {
    foreach ($pattern in @('*Codex*','*OpenAI*','*Antigravity*')) {
        try {
            foreach ($app in @(Get-AppxPackage -Name $pattern -ErrorAction Stop | Select-Object -First 12)) {
                $appx += [ordered]@{ name=[string]$app.Name; version=[string]$app.Version }
            }
        } catch { }
    }
}
$installed = @()
$regKeys = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
foreach ($key in $regKeys) {
    try {
        foreach ($item in @(Get-ItemProperty -Path $key -ErrorAction SilentlyContinue)) {
            $nameProp = $item.PSObject.Properties['DisplayName']
            if ($null -eq $nameProp) { continue }
            $label = [string]$nameProp.Value
            if ($label -match '(?i)Codex|OpenAI|Antigravity|Git for Windows|Google Chrome|Ollama|LM Studio') {
                $versionProp = $item.PSObject.Properties['DisplayVersion']
                $publisherProp = $item.PSObject.Properties['Publisher']
                $version = if ($null -ne $versionProp) { [string]$versionProp.Value } else { '' }
                $publisher = if ($null -ne $publisherProp) { [string]$publisherProp.Value } else { '' }
                $installed += [ordered]@{ name=$label; version=$version; publisher=$publisher }
            }
            if ($installed.Count -ge 40) { break }
        }
    } catch { }
    if ($installed.Count -ge 40) { break }
}

$gpu = [ordered]@{ status = 'NOT_AVAILABLE'; name=''; vram_mib=''; driver='' }
try {
    $nv = Get-Command -Name 'nvidia-smi.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $nv) {
        $output = @(& $nv.Source --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null)
        if ($LASTEXITCODE -eq 0 -and $output.Count -gt 0) {
            $first = ([string]$output[0]).Split(',')
            if ($first.Count -ge 3) {
                $gpu = [ordered]@{ status='DETECTED'; name=$first[0].Trim(); vram_mib=$first[1].Trim(); driver=$first[2].Trim() }
            }
        }
    }
} catch { }

$report = [ordered]@{
    schema = 'RAI_FABRIC_PROVIDER_DISCOVERY/1'
    created_utc = [DateTime]::UtcNow.ToString('o')
    verdict = 'PASS_READONLY_DISCOVERY'
    language = 'ru-RU'
    windows = ($env:OS -eq 'Windows_NT')
    path_discovery = $cmdResults
    known_installation_candidates = @($script:knownPaths.ToArray())
    appx_packages = $appx
    uninstall_metadata = $installed
    gpu = $gpu
    explicit_boundaries = [ordered]@{
        oauth_tokens_read = $false
        auth_profiles_read = $false
        models_launched = $false
        codex_launched = $false
        antigravity_launched = $false
        network_requests = 0
        paid_api_calls = 0
        bpr40_mutations = 0
    }
    interpretation_ru = 'Отсутствие команды в PATH не доказывает, что приложение не установлено. Данные ограничены метаданными.'
    next_cursor = 'RAI-FABRIC/09.7-C-PROVIDER_GATE_AND_OAUTH_CONSENT'
}
$data = $report | ConvertTo-Json -Depth 9 -Compress
[IO.File]::WriteAllText($OutputPath, $data + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
Write-Output 'Диагностика установленных программ завершена.'
