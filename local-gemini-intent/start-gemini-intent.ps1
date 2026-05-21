$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$VenvSitePackages = Join-Path $ScriptDir ".venv\Lib\site-packages"
$SystemPython = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
$Python = if ($SystemPython) { $SystemPython } else { $VenvPython }

if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment not found. Run setup first."
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

if (-not $env:GEMINI_API_KEY) {
    $env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")
}

if (-not $env:GEMINI_MODEL) {
    $env:GEMINI_MODEL = [Environment]::GetEnvironmentVariable("GEMINI_MODEL", "User")
}

if (-not $env:GEMINI_MODEL) {
    $env:GEMINI_MODEL = "gemini-2.5-flash"
}

if (-not $env:POLLINATIONS_API_KEY) {
    $env:POLLINATIONS_API_KEY = [Environment]::GetEnvironmentVariable("POLLINATIONS_API_KEY", "User")
}

if (-not $env:POLLINATIONS_MODEL) {
    $env:POLLINATIONS_MODEL = [Environment]::GetEnvironmentVariable("POLLINATIONS_MODEL", "User")
}

if (-not $env:POLLINATIONS_MODEL) {
    $env:POLLINATIONS_MODEL = "gpt-5-mini"
}

if (-not $env:GEMINI_INTENT_HOST) {
    $env:GEMINI_INTENT_HOST = "127.0.0.1"
}

if (-not $env:GEMINI_INTENT_PORT) {
    $env:GEMINI_INTENT_PORT = "5003"
}

& $Python (Join-Path $ScriptDir "server.py")

