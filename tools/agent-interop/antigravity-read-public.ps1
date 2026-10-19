#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][guid]$ConversationId,
    [ValidateRange(1,10)][int]$Last=3,
    [ValidateRange(128,16384)][int]$MaxChars=4000,
    [int]$GrpcPort=0
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'antigravity-public-view.ps1')
$native=Join-Path $env:LOCALAPPDATA 'Programs/antigravity/resources/bin/language_server_real.exe'
if(-not(Test-Path -LiteralPath $native)){throw 'Native Antigravity CLI not found'}
$devtoolsPort=[int](Get-Content (Join-Path $env:APPDATA 'Antigravity/DevToolsActivePort') -First 1)
$tabs=Invoke-RestMethod "http://127.0.0.1:$devtoolsPort/json/list" -NoProxy -TimeoutSec 10
$page=$tabs|Where-Object {$_.type -eq 'page' -and $_.url -like 'https://127.0.0.1:*'}|Select-Object -First 1
if(-not $page){throw 'No current Antigravity loopback page found'}
$origin=([uri]$page.url).GetLeftPart([UriPartial]::Authority)
$html=(Invoke-WebRequest $origin -NoProxy -SkipCertificateCheck -TimeoutSec 10).Content
$csrf=[regex]::Match($html,'"csrfToken":"([^"]+)"').Groups[1].Value
if(-not $csrf){throw 'Current app configuration has no CSRF capability'}
# On the verified installation gRPC is HTTPS+1. Treat it only as a candidate:
# exact conversation metadata must authenticate before any message is sent.
if($GrpcPort -eq 0){$GrpcPort=([uri]$origin).Port+1}
if($GrpcPort -lt 1 -or $GrpcPort -gt 65535){throw 'Invalid native gRPC port'}
$savedAddress=$env:ANTIGRAVITY_LS_ADDRESS
$savedToken=$env:ANTIGRAVITY_CSRF_TOKEN
try {
    $env:ANTIGRAVITY_LS_ADDRESS="127.0.0.1:$GrpcPort"
    $env:ANTIGRAVITY_CSRF_TOKEN=$csrf
    $raw=& $native agentapi get-conversation-metadata $ConversationId.ToString() 2>&1
    if($LASTEXITCODE -ne 0){throw 'Native metadata authentication failed; no message sent. Rediscover instance/port without elevation.'}
    $metadata=($raw -join "`n")|ConvertFrom-Json
    $rootId=$metadata.response.conversationMetadata.metadata.rootConversationId
    if($rootId -ne $ConversationId.ToString()){throw 'Unexpected root conversation identity; verify child/root relationship manually before sending'}
    $headers=@{'X-Codeium-Csrf-Token'=$csrf;'Connect-Protocol-Version'='1'}
    $endpoint="$origin/exa.language_server_pb.LanguageServerService/"
    $snapshot=Invoke-RestMethod ($endpoint+'GetCascadeTrajectory') -Method Post -ContentType application/json `
        -Body (@{cascadeId=$ConversationId.ToString()}|ConvertTo-Json -Compress) -Headers $headers -NoProxy -SkipCertificateCheck -TimeoutSec 25
    if($snapshot.trajectory.cascadeId -ne $ConversationId.ToString()){throw 'Native trajectory recipient mismatch'}
    Get-RnvPublicView $snapshot -Last $Last -MaxChars $MaxChars
} finally {
    $env:ANTIGRAVITY_LS_ADDRESS=$savedAddress
    $env:ANTIGRAVITY_CSRF_TOKEN=$savedToken
    $snapshot=$null;$metadata=$null;$raw=$null;$csrf=$null;$html=$null;$headers=$null
}
