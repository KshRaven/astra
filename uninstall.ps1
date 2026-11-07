<#
.SYNOPSIS  Remove Astra. Keeps %ProgramData%\astra (config, audit log) unless -Purge is given. Run elevated.
#>
[CmdletBinding()]
param(
  [switch]$Purge,
  [string]$Prefix = (Join-Path $env:ProgramFiles 'Astra'),
  [string]$Conf = (Join-Path $env:ProgramData 'astra')
)
$ErrorActionPreference = 'Stop'
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run as Administrator.' }

if (Get-ScheduledTask -TaskName 'AstraPanel' -ErrorAction SilentlyContinue) {
  Stop-ScheduledTask -TaskName 'AstraPanel' -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName 'AstraPanel' -Confirm:$false
}
Start-Sleep -Seconds 2
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$kept = ($machinePath -split ';') | Where-Object { $_ -and $_ -ne $Prefix }
[Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'Machine')
if (Test-Path -LiteralPath $Prefix) { Remove-Item -LiteralPath $Prefix -Recurse -Force }
if ($Purge) {
  if (Test-Path -LiteralPath $Conf) { Remove-Item -LiteralPath $Conf -Recurse -Force }
  Write-Host 'Config and logs removed.'
} else {
  Write-Host "Kept $Conf (use -Purge to delete)."
}
Write-Host 'astra removed. nginx sites, Task Scheduler tasks (folder \Astra), firewall rules named "Astra:*" and backups it created are left in place.'
