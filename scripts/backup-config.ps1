# Archive the panel config, custom extensions/theme and audit log (contains the token HASH, keep it private). Windows.
param(
  [string]$Source = $(if ($env:ASTRA_HOME) { $env:ASTRA_HOME } else { Join-Path $env:ProgramData 'astra' }),
  [string]$Dest = (Join-Path $HOME ("astra-config-{0}.zip" -f (Get-Date -Format 'yyyy-MM-dd')))
)
$ErrorActionPreference = 'Stop'
Compress-Archive -Path $Source -DestinationPath $Dest -Force
# only the current user and SYSTEM/Administrators may read the archive
& icacls $Dest /inheritance:r /grant:r "${env:USERDOMAIN}\${env:USERNAME}:F" '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
Write-Host "Saved $Dest"
