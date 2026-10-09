# One-shot isolated local smoke test. No cloud model calls; no modification of Codex/BPR40 profiles.
$ErrorActionPreference = 'Stop'
$python = (Get-Command py -ErrorAction SilentlyContinue)
if ($python) { $exe = 'py'; $prefix = @('-3') }
else { $exe = 'python'; $prefix = @() }
$root = Join-Path $env:TEMP ('rai-fabric-demo-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $root | Out-Null
$db = Join-Path $root 'state.sqlite3'
$env:PYTHONPATH = Join-Path (Split-Path $PSScriptRoot -Parent) 'src'
& $exe @prefix -m rai_fabric --db $db init
& $exe @prefix -m rai_fabric --db $db submit --objective 'Smoke-test original queue and checkpoint lifecycle' --provider mock --workspace $root
& $exe @prefix -m rai_fabric --db $db run-once --provider mock
& $exe @prefix -m rai_fabric --db $db tasks
Write-Host "Demo data: $root"
