# Resolve a real Python 3.11+ executable with a bounded managed probe (Windows / PowerShell 7).
# W2 F2.2 candidate patch: no direct PowerShell `& py` and no unbounded PATH alias invocation.
function Resolve-RAiFPython {
    [CmdletBinding()]
    param()
    foreach ($commandName in @('py.exe', 'python.exe')) {
        $application = Get-Command -Name $commandName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $application) { continue }
        $launcher = [string]$application.Source
        if (-not [IO.Path]::IsPathFullyQualified($launcher) -or -not [IO.File]::Exists($launcher)) { continue }
        if ($launcher -match '(?i)[\\/]WindowsApps[\\/]') { continue }
        $probeArguments = [Collections.Generic.List[string]]::new()
        if ($commandName -eq 'py.exe') { [void]$probeArguments.Add('-3') }
        foreach ($argument in @('-X', 'utf8', '-B', '-c', 'import sys; print(sys.executable if sys.version_info >= (3,11) else "")')) {
            [void]$probeArguments.Add($argument)
        }
        $child = [Diagnostics.Process]::new()
        $started = $false
        try {
            $startInfo = [Diagnostics.ProcessStartInfo]::new()
            $startInfo.FileName = $launcher
            $startInfo.UseShellExecute = $false
            $startInfo.CreateNoWindow = $true
            $startInfo.RedirectStandardOutput = $true
            $startInfo.RedirectStandardError = $true
            $startInfo.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
            $startInfo.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
            foreach ($argument in $probeArguments) { [void]$startInfo.ArgumentList.Add($argument) }
            foreach ($key in @('PYTHONHOME','PYTHONPATH','PYTHONINSPECT','PYTHONSTARTUP',
                               'OPENAI_API_KEY','GEMINI_API_KEY','GOOGLE_API_KEY','ANTHROPIC_API_KEY',
                               'AZURE_OPENAI_API_KEY','GITHUB_TOKEN','GH_TOKEN','RAI_LEASE_TOKEN')) {
                [void]$startInfo.Environment.Remove($key)
            }
            $child.StartInfo = $startInfo
            $started = $child.Start()
            if (-not $started) { continue }
            $stdoutTask = $child.StandardOutput.ReadToEndAsync()
            $stderrTask = $child.StandardError.ReadToEndAsync()
            if (-not $child.WaitForExit(8000)) { continue }
            if (-not ($stdoutTask.Wait(3000) -and $stderrTask.Wait(3000))) { continue }
            if ($child.ExitCode -ne 0) { continue }
            $resolved = $stdoutTask.GetAwaiter().GetResult().Trim()
            if ([string]::IsNullOrWhiteSpace($resolved) -or $resolved.Contains("`n")) { continue }
            if (-not [IO.Path]::IsPathFullyQualified($resolved) -or -not [IO.File]::Exists($resolved)) { continue }
            if ($resolved -match '(?i)[\\/]WindowsApps[\\/]') { continue }
            return @{ FilePath = $resolved; Prefix = @() }
        } catch {
            # A failed probe is not a working interpreter. Proceed only if its child is reaped.
        } finally {
            if ($started -and -not $child.HasExited) {
                try { $child.Kill($true); [void]$child.WaitForExit(5000) } catch {}
            }
            $notReaped = ($started -and -not $child.HasExited)
            $child.Dispose()
            if ($notReaped) { throw 'RAIF_PYTHON_PROBE_CHILD_NOT_REAPED' }
        }
    }
    throw 'RAIF_PYTHON_3_11_EXECUTABLE_NOT_RESOLVED'
}
