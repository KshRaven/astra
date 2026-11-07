<#
.SYNOPSIS
  Astra installer for Windows 10/11 and Windows Server 2016 or newer. Run from an elevated PowerShell:
    powershell -ExecutionPolicy Bypass -File .\install.ps1 [-Port 8800] [-InstallPython] [-AllowUserPython]
.DESCRIPTION
  Copies Astra to %ProgramFiles%\Astra, creates %ProgramData%\astra (config, token, logs; ACL: SYSTEM + Administrators),
  adds an `astra` command to the machine PATH and registers a scheduled task "AstraPanel" that starts the panel at boot
  as SYSTEM and restarts it if it stops. The panel listens on all interfaces; restrict it with `astra config set host 127.0.0.1`.
  Developing or just trying it? You do not need this script: `pip install .` then run `astra`.
#>
[CmdletBinding()]
param(
  [int]$Port = 8800,
  [switch]$InstallPython,      # try `winget install Python.Python.3.12` when no suitable Python is found
  [switch]$AllowUserPython,    # accept a Python under C:\Users (SYSTEM may not be able to run it)
  [string]$Prefix = (Join-Path $env:ProgramFiles 'Astra'),
  [string]$Conf = (Join-Path $env:ProgramData 'astra')
)
$ErrorActionPreference = 'Stop'
$TaskName = 'AstraPanel'

$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'Run this script from an elevated (Run as administrator) PowerShell.'
}

function Find-Python {
  $candidates = @(
    @{ Exe = 'py';      Pre = @('-3') },
    @{ Exe = 'python';  Pre = @() },
    @{ Exe = 'python3'; Pre = @() }
  )
  foreach ($c in $candidates) {
    $cmd = Get-Command $c.Exe -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try {
      $out = & $cmd.Source @($c.Pre) -c "import sys; print(sys.executable if sys.version_info >= (3, 9) else '')" 2>$null
      if ($out -and (Test-Path -LiteralPath $out)) { return [string]$out }
    } catch { }   # the Microsoft Store stub fails here: ignore it
  }
  foreach ($p in (Get-ChildItem -Path (Join-Path $env:ProgramFiles 'Python3*\python.exe') -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
    $v = & $p.FullName -c "import sys; print(int(sys.version_info >= (3, 9)))" 2>$null
    if ($v -eq '1') { return $p.FullName }
  }
  return $null
}

Write-Host '==> Looking for Python 3.9+'
$py = Find-Python
if (-not $py -and $InstallPython) {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw 'winget is not available (Windows Server usually lacks it). Install Python 3.9+ for all users from https://www.python.org/downloads/windows/ and run this script again.'
  }
  winget install -e --id Python.Python.3.12 --scope machine --silent --accept-package-agreements --accept-source-agreements
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
  $py = Find-Python
}
if (-not $py) {
  throw 'Python 3.9+ was not found. Install it for all users (python.org, tick "Add to PATH") or re-run with -InstallPython.'
}
if (($py -like (Join-Path $env:SystemDrive 'Users\*')) -and -not $AllowUserPython) {
  throw "Python is installed per user ($py). The panel runs as SYSTEM, which may not be able to start it. Install Python for all users, or pass -AllowUserPython."
}
Write-Host "    using $py"

# Stop a previous install (also covers upgrades) before replacing files
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
  Write-Host '==> Stopping the existing AstraPanel task'
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
}

Write-Host "==> Copying files to $Prefix"
$dest = Join-Path $Prefix 'src'
if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Get-ChildItem -LiteralPath $PSScriptRoot -Force |
  Where-Object { $_.Name -notin @('.git', '.dev-home', '__pycache__') } |
  Copy-Item -Destination $dest -Recurse -Force
# SYSTEM runs this code, so only SYSTEM/Administrators may change it (Users: read and execute)
& icacls $Prefix /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null

Write-Host '==> Creating the astra command'
$wrapper = @"
@echo off
set "ASTRA_HOME=$Conf"
set "PYTHONPATH=$dest"
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
"$py" -m astra %*
"@
Set-Content -LiteralPath (Join-Path $Prefix 'astra.cmd') -Value $wrapper -Encoding ASCII
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if (($machinePath -split ';') -notcontains $Prefix) {
  [Environment]::SetEnvironmentVariable('Path', "$machinePath;$Prefix", 'Machine')
}
$env:Path += ";$Prefix"
$astra = Join-Path $Prefix 'astra.cmd'

Write-Host "==> Initialising config in $Conf"
& $astra init   # prints the admin user name and a generated password (shown once)
if ($LASTEXITCODE) { throw 'astra init failed' }
& $astra config set port "$Port" | Out-Null

Write-Host "==> Registering the scheduled task $TaskName (starts at boot, runs as SYSTEM)"
$log = Join-Path $Conf 'logs\server.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
$action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32\cmd.exe') `
  -Argument "/s /c `"`"$astra`" serve >> `"$log`" 2>&1`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
  -Description 'Astra server control panel' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

Write-Host ''
& $astra doctor
Write-Host ''
Write-Host "Done. The panel runs as the scheduled task $TaskName on port $Port (all interfaces)."
Write-Host 'Allow it through Windows Firewall if you want other computers to reach it:'
Write-Host "    New-NetFirewallRule -DisplayName 'Astra panel' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow"
Write-Host 'Restrict it to this machine with:  astra config set host 127.0.0.1   (then restart the task)'
Write-Host 'Put it behind HTTPS before exposing it to the internet: see nginx\astra.conf.example and docs\SECURITY.md'
Write-Host "Change the password any time with 'astra passwd'. Turn on a second factor in Settings, or run 'astra mfa'."
Write-Host "Control the panel:  schtasks /run /tn $TaskName   |   schtasks /end /tn $TaskName   |   Server log: $log"
