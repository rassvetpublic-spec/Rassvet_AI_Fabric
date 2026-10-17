#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][guid]$ConversationId,
    [string]$MessageFile,
    [switch]$OwnerAuthorized,
    [int]$GrpcPort = 0,
    [string]$QueueRoot = 'C:/CODEX/home/agent-interop/outbox',
    [switch]$Drain
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'antigravity-delivery-policy.ps1')
# Native app credentials remain in this short-lived process only.
$native=Join-Path $env:LOCALAPPDATA 'Programs/antigravity/resources/bin/language_server_real.exe'
if(-not(Test-Path -LiteralPath $native)){throw 'Native Antigravity CLI not found'}
if(($MessageFile -or $Drain) -and -not $OwnerAuthorized){throw 'Sending requires existing human authorization and -OwnerAuthorized'}
if($MessageFile -and $Drain){throw 'Choose MessageFile or Drain, not both'}
$message=$null
if($MessageFile){
    $file=Get-Item -LiteralPath $MessageFile
    if($file.Length -gt 65536){throw 'Message exceeds 64KiB; link an artifact instead'}
    $message=Get-Content -LiteralPath $file.FullName -Raw
    if([string]::IsNullOrWhiteSpace($message)){throw 'Message is empty'}
}
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
    $lastError=''
    $lastStep=@($snapshot.trajectory.steps)|Select-Object -Last 1
    if($lastStep -and $lastStep.type -eq 'CORTEX_STEP_TYPE_ERROR_MESSAGE'){
        $lastError=[string]$lastStep.errorMessage.error.shortError
    }
    $decision=Get-RnvDeliveryDecision ([string]$snapshot.status) $lastError
    $state='STATE_OBSERVED'
    $queuePath=$null
    $recipientQueue=Join-Path $QueueRoot $ConversationId.ToString()
    if($Drain -and (Test-Path -LiteralPath $recipientQueue)){
        $pending=Get-ChildItem -LiteralPath $recipientQueue -Filter '*.json' -File | Where-Object {
            $_.Name -match '^[a-f0-9]{64}\.json$' -and -not(Test-Path -LiteralPath ($_.FullName+'.receipt.json'))
        } | Sort-Object CreationTimeUtc | Select-Object -First 1
        if($pending){
            $queued=Get-Content -LiteralPath $pending.FullName -Raw|ConvertFrom-Json
            if($queued.schema -ne 'RNV_IDLE_MESSAGE/1' -or $queued.destination -ne $ConversationId.ToString() -or
                (Get-RnvMessageKey $queued.destination $queued.message) -ne $pending.BaseName){throw 'Invalid queued message identity/hash'}
            $message=[string]$queued.message
            $queuePath=$pending.FullName
        }
    }
    if($message){
        if(-not $queuePath){
            [void][IO.Directory]::CreateDirectory($recipientQueue)
            $key=Get-RnvMessageKey $ConversationId.ToString() $message
            $queuePath=Join-Path $recipientQueue ($key+'.json')
            if(-not(Test-Path -LiteralPath $queuePath)){
                $entry=@{schema='RNV_IDLE_MESSAGE/1';destination=$ConversationId.ToString();message=$message;
                    created_utc=[DateTimeOffset]::UtcNow.ToString('o');owner_authorized=$true}
                $bytes=[Text.Encoding]::UTF8.GetBytes(($entry|ConvertTo-Json -Depth 5))
                $file=[IO.File]::Open($queuePath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
                try{$file.Write($bytes);$file.Flush($true)}finally{$file.Dispose()}
            }
        }
        $receipt=$queuePath+'.receipt.json'
        $state='QUEUED_LOCAL_NOT_DELIVERED'
        if(Test-Path -LiteralPath $receipt){$state='PREVIOUS_SUBMISSION_REQUIRES_RECEIPT_CHECK'}
        elseif($decision.action -eq 'SEND_WHEN_IDLE'){
            $request=New-RnvIdleRequest $snapshot.trajectory $message
            # Write before submission: an uncertain POST is never retried automatically.
            @{status='SUBMISSION_UNCONFIRMED';utc=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath $receipt
            $null=Invoke-RestMethod ($endpoint+'SendUserCascadeMessage') -Method Post -ContentType application/json `
                -Body ($request|ConvertTo-Json -Depth 60 -Compress) -Headers $headers -NoProxy -SkipCertificateCheck -TimeoutSec 25
            $state='SUBMITTED_WHEN_IDLE_NOT_ACKNOWLEDGED'
            @{status=$state;utc=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath $receipt
        }
    }
    [pscustomobject]@{schema='DIRECT_ANTIGRAVITY_DELIVERY/2';destination=$ConversationId.ToString();status=$state;
        worker_state=$decision.worker_state;native_status=[string]$snapshot.status;action=$decision.action;
        total_steps=$snapshot.numTotalSteps;last_step_type=[string]$lastStep.type;
        last_step_utc=[string]$lastStep.metadata.createdAt;
        recent_actions=@($snapshot.trajectory.steps | Where-Object {
            $_.type -notin @('CORTEX_STEP_TYPE_SYSTEM_MESSAGE','CORTEX_STEP_TYPE_PLANNER_RESPONSE','CORTEX_STEP_TYPE_USER_INPUT')
        } | Select-Object -Last 4 | ForEach-Object {
            [pscustomobject]@{type=[string]$_.type;status=[string]$_.status;created_utc=[string]$_.metadata.createdAt}
        });
        queued_file=$queuePath;utc=[DateTimeOffset]::UtcNow.ToString('o');settings_overridden=$false}
    $snapshot=$null;$request=$null;$queued=$null;$bytes=$null
} finally {
    $env:ANTIGRAVITY_LS_ADDRESS=$savedAddress
    $env:ANTIGRAVITY_CSRF_TOKEN=$savedToken
    $csrf=$null;$html=$null;$raw=$null;$message=$null
}
