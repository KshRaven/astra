param([int]$Port = 8800)

# Developer setup: install in editable mode and run against a throwaway config folder.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not $env:ASTRA_HOME) { $env:ASTRA_HOME = Join-Path (Get-Location) '.dev-home' }
python -m pip install -q -e .
Write-Host "Config folder: $env:ASTRA_HOME  (service/firewall tabs need an elevated shell)"
$PortWasSpecified = $PSBoundParameters.ContainsKey('Port')
$PortInUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($PortInUse) {
	if ($PortWasSpecified) {
		throw "Port $Port is already in use. Choose another port with -Port, for example: .\scripts\dev.ps1 -Port $($Port + 1)"
	}
	$DefaultPort = $Port
	do { $Port++ } while (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
	Write-Warning "Port $DefaultPort is already in use; using $Port instead."
}
astra web --host 127.0.0.1 --port $Port @args
