$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run setup first."
}

if (-not $env:WHISPER_MODEL) {
    $env:WHISPER_MODEL = "base"
}

if (-not $env:WHISPER_DEVICE) {
    $env:WHISPER_DEVICE = "cpu"
}

if (-not $env:WHISPER_COMPUTE_TYPE) {
    $env:WHISPER_COMPUTE_TYPE = "int8"
}

if (-not $env:WHISPER_LANGUAGE) {
    $env:WHISPER_LANGUAGE = "en"
}

if (-not $env:WHISPER_WAKE_INITIAL_PROMPT) {
    $env:WHISPER_WAKE_INITIAL_PROMPT = "assistant"
}

if (-not $env:WHISPER_COMMAND_INITIAL_PROMPT) {
    $env:WHISPER_COMMAND_INITIAL_PROMPT = "voice assistant command send email to at dot dypiu dot ac dot in subject message reminder"
}

if (-not $env:WHISPER_WAKE_HOTWORDS) {
    $env:WHISPER_WAKE_HOTWORDS = "assistant"
}

if (-not $env:WHISPER_COMMAND_HOTWORDS) {
    $env:WHISPER_COMMAND_HOTWORDS = "assistant email reminder subject message at dot dypiu ac in"
}

if (-not $env:DEEPGRAM_API_KEY) {
    $env:DEEPGRAM_API_KEY = [Environment]::GetEnvironmentVariable("DEEPGRAM_API_KEY", "User")
}

if (-not $env:ELEVENLABS_API_KEY) {
    $env:ELEVENLABS_API_KEY = [Environment]::GetEnvironmentVariable("ELEVENLABS_API_KEY", "User")
}

if (-not $env:TRANSCRIBE_PROVIDER) {
    if ($env:DEEPGRAM_API_KEY) {
        $env:TRANSCRIBE_PROVIDER = "deepgram"
    }
    elseif ($env:ELEVENLABS_API_KEY) {
        $env:TRANSCRIBE_PROVIDER = "elevenlabs"
    }
    else {
        $env:TRANSCRIBE_PROVIDER = "whisper"
    }
}

if (-not $env:DEEPGRAM_MODEL) {
    $env:DEEPGRAM_MODEL = "nova-3"
}

if (-not $env:ELEVENLABS_MODEL_ID) {
    $env:ELEVENLABS_MODEL_ID = "scribe_v1"
}

if (-not $env:WHISPER_FALLBACK_ENABLED) {
    $env:WHISPER_FALLBACK_ENABLED = "false"
}

& $Python (Join-Path $ScriptDir "server.py")

