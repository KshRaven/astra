# Debug helper (Windows): setup check + task state + recent logs.
$astra = Join-Path $env:ProgramFiles 'Astra\astra.cmd'
if (Test-Path $astra) { $run = { & $astra @args } }
else {
  Set-Location (Split-Path -Parent $PSScriptRoot)
  $run = { if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m astra @args } else { & python -m astra @args } }
}
& $run doctor
Write-Host "`n--- scheduled task ---"
$t = Get-ScheduledTask -TaskName 'AstraPanel' -ErrorAction SilentlyContinue
if ($t) { $t | Get-ScheduledTaskInfo | Format-List TaskName, LastRunTime, LastTaskResult, NextRunTime; "State: $($t.State)" } else { '(not installed as a task)' }
Write-Host "`n--- last 20 server log lines ---"
$log = Join-Path $env:ProgramData 'astra\logs\server.log'
if (Test-Path $log) { Get-Content $log -Tail 20 } else { '(no server.log yet)' }
Write-Host "`n--- last 10 audit events ---"
& $run logs -n 10
