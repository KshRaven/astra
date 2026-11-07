# Developer setup: install in editable mode and run against a throwaway config folder.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not $env:ASTRA_HOME) { $env:ASTRA_HOME = Join-Path (Get-Location) '.dev-home' }
python -m pip install -q -e .
Write-Host "Config folder: $env:ASTRA_HOME  (service/firewall tabs need an elevated shell)"
astra web --host 127.0.0.1 @args
