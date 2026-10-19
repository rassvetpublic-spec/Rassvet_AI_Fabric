# Pure decisions; this file never contacts or interrupts a worker.
function Get-RnvDeliveryDecision([string]$NativeStatus, [string]$LastError = '') {
    if ($LastError -match '(?i)FAILED_PRECONDITION|location is not supported|permission.denied|quota.exceeded') {
        return [pscustomobject]@{worker_state='BLOCKED';action='HOLD'}
    }
    switch ($NativeStatus) {
        'CASCADE_RUN_STATUS_RUNNING' { return [pscustomobject]@{worker_state='BUSY';action='QUEUE'} }
        'CASCADE_RUN_STATUS_IDLE' { return [pscustomobject]@{worker_state='IDLE';action='SEND_WHEN_IDLE'} }
        default { return [pscustomobject]@{worker_state='UNKNOWN';action='HOLD'} }
    }
}
function Get-RnvMessageKey([string]$Destination, [string]$Message) {
    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($Destination + "`n" + $Message))).ToLowerInvariant()
}
function New-RnvIdleRequest($Trajectory, [string]$Message) {
    $user = @($Trajectory.steps | Where-Object { $_.PSObject.Properties['userInput'] } |
        Where-Object { $_.userInput.PSObject.Properties['userAgentSpec'] }) | Select-Object -Last 1
    $generator = @($Trajectory.generatorMetadata | Where-Object { $_.PSObject.Properties['plannerConfig'] }) | Select-Object -Last 1
    if (-not $generator -and $Trajectory.PSObject.Properties['executorMetadatas']) {
        $executor = @($Trajectory.executorMetadatas | Where-Object { $_.PSObject.Properties['cascadeConfig'] -and $_.cascadeConfig.plannerConfig.planModel -and $_.cascadeConfig.plannerConfig.modelName }) | Select-Object -Last 1
        if ($executor) { $generator = $executor.cascadeConfig }
    }
    if (-not $user -or -not $generator -or -not $generator.plannerConfig.planModel -or -not $generator.plannerConfig.modelName) {
        throw 'TARGET_SETTINGS_UNAVAILABLE: no delivery; do not substitute defaults'
    }
    @{
        cascadeId = $Trajectory.cascadeId
        items = @(@{text=$Message})
        customAgentSpec = $user.userInput.userAgentSpec
        cascadeConfig = @{plannerConfig=@{
            planModel=$generator.plannerConfig.planModel
            modelName=$generator.plannerConfig.modelName
        }}
        deliveryStrategy = 'MESSAGE_DELIVERY_STRATEGY_WHEN_IDLE'
        messageOrigin = 'AGENT_MESSAGE_ORIGIN_SDK_EXECUTABLE'
    }
}
