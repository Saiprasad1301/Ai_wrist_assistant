# AI Wrist Assistant Dashboard

Local Windows dashboard for starting, stopping, monitoring, and presenting the AI Wrist Assistant system.

## What It Starts

- n8n workflow server
- ESP32 serial monitor on the configured COM port
- Speech-to-text service in `local-whisper`
- Intent/LLM service in `local-gemini-intent`
- Text-to-speech service in `local-gtts`

## Folder Structure

```text
ai-wrist-dashboard/
  backend/
    src/
      config.js
      server.js
      serviceManager.js
      store.js
      websocket.js
    data/
      settings.json
      tasks.json
      logs.json
    package.json
  frontend/
    src/
      main.jsx
      styles.css
    index.html
    package.json
    tailwind.config.js
    postcss.config.js
  package.json
  README.md
```

## Install

From PowerShell:

```powershell
cd "C:\n8n automation\ai-wrist-dashboard"
npm run install:all
```

## Run

Start the dashboard:

```powershell
cd "C:\n8n automation\ai-wrist-dashboard"
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

Backend API:

```text
http://127.0.0.1:8787
```

Stop only the dashboard app:

```powershell
npm run stop
```

## Configure COM Port

Open the dashboard Settings page and edit:

- COM port, for example `COM13`
- Baud rate, usually `115200`
- ESP32 command arguments

The default ESP32 command is:

```powershell
& "C:\Program Files\Arduino CLI\arduino-cli.exe" monitor -p COM13 -c baudrate=115200,dtr=off,rts=off
```

In Settings, `{COM_PORT}` and `{BAUD_RATE}` are replaced automatically.

## API Endpoints

- `POST /api/start`
- `POST /api/stop`
- `POST /api/restart`
- `GET /api/status`
- `GET /api/last-successful-ai-action`
- `GET /api/last-execution-status`
- `GET /api/tasks`
- `POST /api/tasks`
- `GET /api/logs`
- `DELETE /api/logs`
- `GET /api/settings`
- `PUT /api/settings`

WebSocket logs:

```text
ws://127.0.0.1:8787/ws
```

## Error Handling

If a command is missing, a folder path is wrong, COM port is unavailable, or a process crashes:

- Service card changes state
- Error appears in Error Logs
- A failed task is added to task history
- Other services keep running

## Notes

- This dashboard starts child processes with `child_process.spawn`.
- Stop uses Windows `taskkill /T /F` so child processes are closed too.
- Logs and tasks are stored locally in JSON files inside `backend/data`.
- No API keys are stored in this project. Your existing Python scripts load keys from Windows environment variables.
