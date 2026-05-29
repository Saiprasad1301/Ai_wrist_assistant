# n8n Workflow Export

This folder contains a GitHub-safe n8n workflow export for the AI Wrist Assistant.

## Included File

```text
production-ready-workflow.json
```

This export has been sanitized before committing:

- Workflow is inactive by default.
- n8n credential bindings were removed.
- Webhook instance IDs were removed.
- API keys and local secrets are not included.
- The Google Calendar ID is replaced with `YOUR_GOOGLE_CALENDAR_ID`.

## Import Steps

1. Open n8n.
2. Import `production-ready-workflow.json`.
3. Reconnect your Gmail OAuth2 credential on the Gmail node.
4. Reconnect your Google Calendar OAuth2 credential on the Calendar node.
5. Replace `YOUR_GOOGLE_CALENDAR_ID` with your real calendar ID.
6. Confirm these local services are running:

```text
http://127.0.0.1:5001/tts
http://127.0.0.1:5002/transcribe
http://127.0.0.1:5003/intent
```

7. Activate or publish the workflow only after local testing.

## Expected Webhook

The ESP32 firmware should call this path on your laptop IP:

```text
http://YOUR_PC_LAN_IP:5678/webhook/voice
```

Do not use `localhost` or `127.0.0.1` in ESP32 firmware because the ESP32 needs to reach the laptop over Wi-Fi.
