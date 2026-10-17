# Pure projection: never includes private thinking, settings, credentials or userAgentSpec.
function Get-RnvPublicView($Snapshot, [int]$Last=3, [int]$MaxChars=4000) {
    if($Last -lt 1 -or $Last -gt 10 -or $MaxChars -lt 1 -or $MaxChars -gt 16384){
        throw 'PUBLIC_VIEW_LIMIT_INVALID'
    }
    $steps=@($Snapshot.trajectory.steps | Where-Object {
        $_.PSObject.Properties['plannerResponse'] -and
        $_.plannerResponse.PSObject.Properties['response'] -and
        $_.plannerResponse.response -is [string] -and
        -not [string]::IsNullOrWhiteSpace($_.plannerResponse.response)
    } | Select-Object -Last $Last)
    $messages=@($steps | ForEach-Object {
        $body=[string]$_.plannerResponse.response
        $utc=$null
        if($_.PSObject.Properties['metadata'] -and $_.metadata.PSObject.Properties['createdAt']){
            $utc=[string]$_.metadata.createdAt
        }
        [pscustomobject]@{
            kind='assistant_public';created_utc=$utc
            text=$body.Substring(0,[Math]::Min($MaxChars,$body.Length))
            truncated=($body.Length -gt $MaxChars)
        }
    })
    [pscustomobject]@{
        schema='FLEET_ANTIGRAVITY_PUBLIC_VIEW/1';destination=$Snapshot.trajectory.cascadeId
        native_status=$Snapshot.status;total_steps=$Snapshot.numTotalSteps
        public_messages=$messages
    }
}
