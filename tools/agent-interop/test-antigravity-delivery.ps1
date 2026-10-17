$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'antigravity-delivery-policy.ps1')
$cases=@(
 @('CASCADE_RUN_STATUS_RUNNING','','BUSY','QUEUE'),
 @('CASCADE_RUN_STATUS_IDLE','','IDLE','SEND_WHEN_IDLE'),
 @('CASCADE_RUN_STATUS_RUNNING','FAILED_PRECONDITION: User location is not supported','BLOCKED','HOLD'),
 @('CASCADE_RUN_STATUS_IDLE','FAILED_PRECONDITION: User location is not supported','BLOCKED','HOLD'),
 @('CASCADE_RUN_STATUS_RUNNING','API error500','BUSY','QUEUE'),
 @('CASCADE_RUN_STATUS_UNSPECIFIED','','UNKNOWN','HOLD')
)
foreach($case in $cases){$r=Get-RnvDeliveryDecision $case[0] $case[1];if($r.worker_state -ne $case[2] -or $r.action -ne $case[3]){throw ('Decision failure '+($case -join ','))}}
$trajectory=[pscustomobject]@{cascadeId='00000000-0000-4000-8000-000000000001';steps=@([pscustomobject]@{userInput=[pscustomobject]@{userAgentSpec=[pscustomobject]@{agent='preserve-me'}}});generatorMetadata=@([pscustomobject]@{plannerConfig=[pscustomobject]@{planModel='preserve-model';modelName='preserve-name'}})}
$r=New-RnvIdleRequest $trajectory 'test message'
if($r.deliveryStrategy -ne 'MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE' -or $r.cascadeId -ne $trajectory.cascadeId -or $r.customAgentSpec.agent -ne 'preserve-me' -or $r.cascadeConfig.plannerConfig.planModel -ne 'preserve-model'){throw 'Idle payload/settings failure'}
$id1=Get-RnvMessageKey $trajectory.cascadeId 'same';$id2=Get-RnvMessageKey $trajectory.cascadeId 'same';$id3=Get-RnvMessageKey '00000000-0000-4000-8000-000000000002' 'same';if($id1 -ne $id2 -or $id1 -eq $id3){throw 'Dedup/recipient failure'}
try{New-RnvIdleRequest ([pscustomobject]@{cascadeId=$trajectory.cascadeId;steps=@();generatorMetadata=@()}) 'message';throw 'Missing settings accepted'}catch{if($_.Exception.Message -eq 'Missing settings accepted'){throw}}
Write-Output 'PASS 9 delivery-policy checks; native sends=0'

