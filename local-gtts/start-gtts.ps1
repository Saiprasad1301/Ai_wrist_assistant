$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$VenvSitePackages = Join-Path $ScriptDir ".venv\Lib\site-packages"
$SystemPython = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
$Python = if ($SystemPython) { $SystemPython } else { $VenvPython }

if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment not found. Run: py -3.11 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

if (-not (Test-Path $Python)) {
    throw "Python executable not found."
}

if ($Python -ne $VenvPython) {
    $existingPythonPath = $env:PYTHONPATH
    if ($existingPythonPath) {
        $env:PYTHONPATH = "$VenvSitePackages;$existingPythonPath"
    } else {
        $env:PYTHONPATH = $VenvSitePackages
    }
}

if (-not $env:GTTS_LANGUAGE) {
    $env:GTTS_LANGUAGE = "en"
}

& $Python (Join-Path $ScriptDir "server.py")
