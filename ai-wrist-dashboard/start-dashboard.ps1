$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $root ".runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Test-PortInUse {
  param([int]$Port)
  return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

if (-not (Test-PortInUse 8787)) {
  $backend = Start-Process `
    -FilePath "node.exe" `
    -ArgumentList @("backend\src\server.js") `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $runtime "backend.out.log") `
    -RedirectStandardError (Join-Path $runtime "backend.err.log") `
    -PassThru
  Set-Content -Path (Join-Path $runtime "backend.pid") -Value $backend.Id
}

if (-not (Test-PortInUse 5173)) {
  $frontend = Start-Process `
    -FilePath "npm.cmd" `
    -ArgumentList @("--prefix", "frontend", "run", "dev") `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $runtime "frontend.out.log") `
    -RedirectStandardError (Join-Path $runtime "frontend.err.log") `
    -PassThru
  Set-Content -Path (Join-Path $runtime "frontend.pid") -Value $frontend.Id
}

Start-Sleep -Seconds 2
Write-Host "Dashboard API: http://127.0.0.1:8787"
Write-Host "Dashboard UI : http://127.0.0.1:5173"
