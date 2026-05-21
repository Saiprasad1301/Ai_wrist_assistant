# AI Wrist Assistant

Local Windows dashboard + ESP32-C3 voice assistant project.

## Main Parts

- `ai-wrist-dashboard`: Node/Express backend and React dashboard for starting/stopping services and watching logs.
- `esp32c3-n8n-voice-client`: ESP32-C3 firmware for INMP441 microphone, wake-word upload, n8n command upload, and MAX98357A speaker output.
- `local-whisper`: local STT gateway with Deepgram/ElevenLabs/Whisper provider support.
- `local-gemini-intent`: local intent/LLM gateway.
- `local-gtts`: local TTS service returning WAV audio.

## Secrets

This repository intentionally does not include live API keys, Wi-Fi passwords, local dashboard state, logs, generated audio, or raw n8n exports that may contain credentials.

Use `.env.example`, `ai-wrist-dashboard/backend/data/settings.example.json`, and `esp32c3-n8n-voice-client/voice_config.example.h` as templates.

## Quick Start

1. Install Node.js, Python 3.11, Arduino CLI, n8n, and Git.
2. Copy `.env.example` to `.env` or set the listed values as Windows user environment variables.
3. Copy `esp32c3-n8n-voice-client/voice_config.example.h` to `voice_config.h` and fill in Wi-Fi and PC LAN IP.
4. Install backend/frontend dependencies:

```powershell
cd ai-wrist-dashboard\backend
npm install
cd ..\frontend
npm install
```

5. Start the dashboard from `ai-wrist-dashboard` using the existing package scripts.

## Notes

Keep the GitHub repo private if you plan to add real n8n exports or credentials later.
