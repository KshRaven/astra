# Try every feature in a throwaway sandbox (Windows): separate config folder, e-mail codes printed to this console.
# Usage: tests\demo.ps1 [-Port 8800]    Then: Settings -> Multi-factor sign-in -> E-mail codes -> any address.
param([int]$Port = 8800)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
function Py { if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 @args } else { & python @args } }
$env:ASTRA_HOME = Join-Path ([IO.Path]::GetTempPath()) ('astra-demo-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$env:ASTRA_DEV = '1'
Py -m astra init
# edit the JSON directly: quoting JSON on a native command line differs between Windows PowerShell 5.1 and 7
$path = Join-Path $env:ASTRA_HOME 'config.json'
$cfg = Get-Content $path -Raw | ConvertFrom-Json
$cfg.port = $Port
$cfg.smtp = [pscustomobject]@{ host = 'console'; port = 587; security = 'starttls'; user = ''; password = ''; from = 'demo@localhost' }
$cfg.operator = [pscustomobject]@{ name = 'Demo operator'; email = 'you@example.com'; address = '' }
$cfg | ConvertTo-Json -Depth 6 | Set-Content -Path $path -Encoding UTF8
Write-Host "Open http://127.0.0.1:$Port  | sandbox: $env:ASTRA_HOME | Ctrl+C to stop"
Py -m astra serve
