$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'antigravity-public-view.ps1')
$snapshot=[pscustomobject]@{
    status='CASCADE_RUN_STATUS_IDLE';numTotalSteps=3
    trajectory=[pscustomobject]@{
        cascadeId='00000000-0000-4000-8000-000000000001'
        plannerConfig=@{secret='PRIVATE_SETTINGS_SENTINEL'}
        steps=@(
            [pscustomobject]@{plannerResponse=[pscustomobject]@{response='old answer';thinking='PRIVATE_THINKING_SENTINEL'}}
            [pscustomobject]@{userInput=@{userAgentSpec='PRIVATE_PROMPT_SENTINEL'}}
            [pscustomobject]@{plannerResponse=[pscustomobject]@{response='final answer';thinking='PRIVATE_THINKING_SENTINEL'};metadata=@{createdAt='2026-10-18T00:00:00Z'}}
        )
    }
}
$r=Get-RnvPublicView $snapshot -Last 1 -MaxChars 5
if($r.public_messages.Count -ne 1 -or $r.public_messages[0].text -ne 'final' -or -not $r.public_messages[0].truncated){throw 'Last/truncation check failed'}
$json=$r|ConvertTo-Json -Depth 10
if($json -match 'PRIVATE_.*_SENTINEL|thinking|plannerConfig|userAgentSpec'){throw 'Private field leaked'}
if($r.destination -ne $snapshot.trajectory.cascadeId -or $r.native_status -ne $snapshot.status){throw 'Identity/state check failed'}
$empty=[pscustomobject]@{status='CASCADE_RUN_STATUS_IDLE';numTotalSteps=0;trajectory=[pscustomobject]@{cascadeId=$snapshot.trajectory.cascadeId;steps=@()}}
if((Get-RnvPublicView $empty).public_messages.Count -ne 0){throw 'Empty view check failed'}
try {Get-RnvPublicView $snapshot -Last 0;throw 'Invalid limits accepted'}catch{if($_.Exception.Message -eq 'Invalid limits accepted'){throw}}
'PASS 5 public-view checks; native sends=0'
