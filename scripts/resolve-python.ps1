# Resolve a runnable Python; WindowsApps AppExecutionAliases can exist but fail (9009).
function Resolve-RAiFPython {
    foreach ($commandName in @('py', 'python')) {
        if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) { continue }
        $prefixArgs = if ($commandName -eq 'py') { @('-3') } else { @() }
        try {
            $probeOutput = @(& $commandName @prefixArgs -c 'import sys; print("RAIF_PYTHON_READY" if sys.version_info >= (3, 11) else "RAIF_PYTHON_TOO_OLD")' 2>$null)
            if ($LASTEXITCODE -eq 0 -and $probeOutput -contains 'RAIF_PYTHON_READY') {
                return @{ FilePath = $commandName; Prefix = $prefixArgs }
            }
        } catch {
            # The candidate is absent, fails to start, or is only an AppExecutionAlias.
        }
    }
    throw 'Python 3.11+ was not found as a working executable (py -3 or python).'
}
