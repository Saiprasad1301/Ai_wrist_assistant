import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const ROOT_DIR = path.resolve(__dirname, "..");
export const DATA_DIR = path.join(ROOT_DIR, "data");
export const AUTOMATION_ROOT = path.resolve(ROOT_DIR, "..", "..");
export const SETTINGS_PATH = path.join(DATA_DIR, "settings.json");
export const TASKS_PATH = path.join(DATA_DIR, "tasks.json");
export const LOGS_PATH = path.join(DATA_DIR, "logs.json");
export const LAST_SUCCESSFUL_AI_ACTION_PATH = path.join(DATA_DIR, "last-successful-ai-action.json");
export const LAST_EXECUTION_STATUS_PATH = path.join(DATA_DIR, "last-execution-status.json");
export const INTENT_SERVICE_LOG_PATH = path.join(AUTOMATION_ROOT, "local-gemini-intent", "service.err.log");

export const SERVICE_DEFINITIONS = {
  esp32: {
    label: "ESP32 Serial",
    logTab: "esp32",
    statusKey: "esp32",
    healthUrl: null
  },
  n8n: {
    label: "n8n Server",
    logTab: "n8n",
    statusKey: "n8n",
    healthUrl: "http://127.0.0.1:5678/healthz"
  },
  stt: {
    label: "Mic/STT Service",
    logTab: "mic",
    statusKey: "mic",
    healthUrl: "http://127.0.0.1:5002/health"
  },
  intent: {
    label: "Intent/LLM Service",
    logTab: "workflow",
    statusKey: "workflow",
    healthUrl: "http://127.0.0.1:5003/health"
  },
  tts: {
    label: "TTS Service",
    logTab: "workflow",
    statusKey: "tts",
    healthUrl: "http://127.0.0.1:5001/health"
  }
};

export const defaultSettings = {
  comPort: "COM13",
  baudRate: "115200",
  autoStartServices: ["n8n", "stt", "intent", "tts", "esp32"],
  commands: {
    n8n: {
      command: "node.exe",
      args: ["C:\\Users\\Dhruva\\AppData\\Roaming\\npm\\node_modules\\n8n\\bin\\n8n", "start"],
      cwd: "C:\\n8n automation",
      env: {
        N8N_HOST: "0.0.0.0",
        N8N_PORT: "5678",
        N8N_PROTOCOL: "http",
        WEBHOOK_URL: "http://10.73.139.69:5678/"
      },
      enabled: true
    },
    stt: {
      command: "powershell.exe",
      args: ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\\n8n automation\\local-whisper\\start-whisper.ps1"],
      cwd: "C:\\n8n automation\\local-whisper",
      enabled: true
    },
    intent: {
      command: "powershell.exe",
      args: ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:\\n8n automation\\local-gemini-intent\\start-gemini-intent.ps1"],
      cwd: "C:\\n8n automation\\local-gemini-intent",
      enabled: true
    },
    tts: {
      command: "C:\\n8n automation\\local-gtts\\.venv\\Scripts\\python.exe",
      args: ["C:\\n8n automation\\local-gtts\\server.py"],
      cwd: "C:\\n8n automation\\local-gtts",
      env: {
        GTTS_LANGUAGE: "en"
      },
      enabled: true
    },
    esp32: {
      command: "powershell.exe",
      args: [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "C:\\n8n automation\\ai-wrist-dashboard\\backend\\scripts\\serial-monitor.ps1",
        "-Port",
        "{COM_PORT}",
        "-BaudRate",
        "{BAUD_RATE}"
      ],
      cwd: "C:\\n8n automation",
      enabled: true
    }
  }
};

export async function ensureDataFiles() {
  await fs.mkdir(DATA_DIR, { recursive: true });
  await ensureJsonFile(SETTINGS_PATH, defaultSettings);
  await ensureJsonFile(TASKS_PATH, []);
  await ensureJsonFile(LOGS_PATH, []);
  await ensureJsonFile(LAST_SUCCESSFUL_AI_ACTION_PATH, null);
  await ensureJsonFile(LAST_EXECUTION_STATUS_PATH, null);
}

export async function ensureJsonFile(filePath, fallback) {
  try {
    await fs.access(filePath);
  } catch {
    await fs.writeFile(filePath, `${JSON.stringify(fallback, null, 2)}\n`, "utf8");
  }
}

export async function readJson(filePath, fallback) {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export async function writeJson(filePath, value) {
  await fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}
