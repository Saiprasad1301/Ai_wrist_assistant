$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $root ".runtime"

foreach ($name in @("backend", "frontend")) {
  $pidPath = Join-Path $runtime "$name.pid"
  if (Test-Path $pidPath) {
    $processId = Get-Content $pidPath | Select-Object -First 1
    if ($processId) {
      Stop-Process -Id $processId -Force
    }
    Remove-Item $pidPath -Force
  }
}

foreach ($port in @(8787, 5173)) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
      Stop-Process -Id $_ -Force
    }
}

Write-Host "Dashboard stop requested."
