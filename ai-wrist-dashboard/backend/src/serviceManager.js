import { spawn } from "node:child_process";
import fs from "node:fs";
import { SERVICE_DEFINITIONS, SETTINGS_PATH, defaultSettings, readJson, writeJson } from "./config.js";
import {
  addTask,
  appendLog,
  consumePendingSuccessfulAiAction,
  inferExecutionStatusFromLog,
  inferLatestSuccessfulAiActionFromIntentLog,
  inferSuccessfulAiActionFromLog,
  inferSuccessfulAiActionFromTask,
  inferTaskFromLog,
  isSpeakerPlaybackSuccess,
  rememberPendingSuccessfulAiActionFromIntentLine,
  updateLastExecutionStatus,
  updateLastSuccessfulAiAction
} from "./store.js";
import { broadcast } from "./websocket.js";

const processes = new Map();
const serviceState = new Map();
const stoppingServices = new Set();

const ORPHAN_CLEANUP = {
  esp32: {
    ports: [],
    patterns: ["*arduino-cli.exe* monitor *", "*serial-monitor.ps1*"]
  },
  n8n: {
    ports: [5678],
    patterns: ["*node_modules*n8n*bin*n8n*", "* n8n start*"]
  },
  stt: {
    ports: [5002],
    patterns: ["*local-whisper*server.py*", "*local-whisper*start-whisper.ps1*"]
  },
  intent: {
    ports: [5003],
    patterns: ["*local-gemini-intent*server.py*", "*local-gemini-intent*start-gemini-intent.ps1*"]
  },
  tts: {
    ports: [5001],
    patterns: ["*local-gtts*server.py*", "*local-gtts*start-gtts.ps1*"]
  }
};

for (const serviceId of Object.keys(SERVICE_DEFINITIONS)) {
  serviceState.set(serviceId, {
    id: serviceId,
    label: SERVICE_DEFINITIONS[serviceId].label,
    running: false,
    status: "Stopped",
    pid: null,
    startedAt: null,
    lastExitCode: null
  });
}

export async function getSettings() {
  const settings = await readJson(SETTINGS_PATH, defaultSettings);
  return {
    ...defaultSettings,
    ...settings,
    commands: {
      ...defaultSettings.commands,
      ...(settings.commands || {})
    }
  };
}

export async function saveSettings(settings) {
  const next = {
    ...defaultSettings,
    ...settings,
    commands: {
      ...defaultSettings.commands,
      ...(settings.commands || {})
    }
  };
  await writeJson(SETTINGS_PATH, next);
  return next;
}

export function getStatus() {
  const services = {};
  for (const [id, state] of serviceState.entries()) {
    services[id] = state;
  }
  return {
    services,
    overallRunning: Object.values(services).some((service) => service.running),
    timestamp: new Date().toISOString()
  };
}

export async function startAll() {
  const settings = await getSettings();
  const services = settings.autoStartServices || Object.keys(SERVICE_DEFINITIONS);
  const results = [];
  for (const serviceId of services) {
    results.push(await startService(serviceId, settings));
  }
  if (results.length && results.every((result) => result.ok)) {
    await publishLastExecutionStatus({
      title: "Start All completed",
      category: "Service command",
      message: "Start command completed for all enabled dashboard services.",
      source: "dashboard"
    });
  }
  return results;
}

export async function stopAll() {
  const results = [];
  for (const serviceId of Object.keys(SERVICE_DEFINITIONS)) {
    results.push(await stopService(serviceId));
  }
  if (results.length && results.every((result) => result.ok)) {
    await publishLastExecutionStatus({
      title: "Stop All completed",
      category: "Service command",
      message: "Stop command completed for all dashboard services.",
      source: "dashboard"
    });
  }
  return results;
}

export async function restartAll() {
  await stopAll();
  await new Promise((resolve) => setTimeout(resolve, 1200));
  const results = await startAll();
  if (results.length && results.every((result) => result.ok)) {
    await publishLastExecutionStatus({
      title: "Restart All completed",
      category: "Service command",
      message: "Restart command completed for all enabled dashboard services.",
      source: "dashboard"
    });
  }
  return results;
}

export async function startService(serviceId, providedSettings = null) {
  if (!SERVICE_DEFINITIONS[serviceId]) {
    throw new Error(`Unknown service: ${serviceId}`);
  }
  if (processes.has(serviceId)) {
    return { serviceId, ok: true, message: "Already running" };
  }

  const settings = providedSettings || (await getSettings());
  const commandConfig = settings.commands?.[serviceId];
  if (!commandConfig || commandConfig.enabled === false) {
    updateService(serviceId, { running: false, status: "Disabled" });
    return { serviceId, ok: false, message: "Service disabled in settings" };
  }

  if (!commandConfig.command) {
    updateService(serviceId, { running: false, status: "Missing command" });
    await emitLog(serviceId, "error", "Command is missing. Open Settings and configure this service.");
    return { serviceId, ok: false, message: "Missing command" };
  }

  if (commandConfig.cwd && !fs.existsSync(commandConfig.cwd)) {
    updateService(serviceId, { running: false, status: "Bad working folder" });
    await emitLog(serviceId, "error", `Working folder does not exist: ${commandConfig.cwd}`);
    return { serviceId, ok: false, message: "Bad working folder" };
  }

  const args = replaceTokens(commandConfig.args || [], settings);
  const command = replaceTokens(commandConfig.command, settings);

  try {
    const child = spawn(command, args, {
      cwd: commandConfig.cwd || process.cwd(),
      env: { ...process.env, ...(commandConfig.env || {}) },
      windowsHide: true,
      shell: false
    });

    processes.set(serviceId, child);
    updateService(serviceId, {
      running: true,
      status: "Running",
      pid: child.pid,
      startedAt: new Date().toISOString(),
      lastExitCode: null
    });

    await emitLog(serviceId, "info", `Started ${SERVICE_DEFINITIONS[serviceId].label} (PID ${child.pid})`);
    await publishLastExecutionStatus({
      title: `${SERVICE_DEFINITIONS[serviceId].label} started`,
      category: "Service command",
      message: `${SERVICE_DEFINITIONS[serviceId].label} started successfully.`,
      source: serviceId
    });

    child.stdout.on("data", (chunk) => handleOutput(serviceId, "info", chunk));
    child.stderr.on("data", (chunk) => handleOutput(serviceId, "error", chunk));
    child.on("error", (error) => handleProcessError(serviceId, error));
    child.on("exit", (code, signal) => handleExit(serviceId, code, signal));

    return { serviceId, ok: true, pid: child.pid };
  } catch (error) {
    updateService(serviceId, { running: false, status: "Start failed", pid: null });
    await emitLog(serviceId, "error", `Failed to start: ${error.message}`);
    return { serviceId, ok: false, message: error.message };
  }
}

export async function stopService(serviceId) {
  const child = processes.get(serviceId);
  if (!child) {
    const cleanup = await cleanupServiceOrphans(serviceId);
    updateService(serviceId, { running: false, status: "Stopped", pid: null });
    if (cleanup.killedPids.length) {
      await emitLog(serviceId, "warning", `Stopped orphan process IDs: ${cleanup.killedPids.join(", ")}`);
    }
    await publishLastExecutionStatus({
      title: `${SERVICE_DEFINITIONS[serviceId].label} stopped`,
      category: "Service command",
      message: cleanup.killedPids.length
        ? `${SERVICE_DEFINITIONS[serviceId].label} orphan processes stopped.`
        : `${SERVICE_DEFINITIONS[serviceId].label} is already stopped.`,
      source: serviceId
    });
    return {
      serviceId,
      ok: true,
      message: cleanup.killedPids.length ? "Stopped orphan processes" : "Already stopped",
      killedPids: cleanup.killedPids
    };
  }

  await emitLog(serviceId, "warning", "Stopping service...");
  stoppingServices.add(serviceId);
  await killProcessTree(child.pid);
  const cleanup = await cleanupServiceOrphans(serviceId);
  processes.delete(serviceId);
  updateService(serviceId, { running: false, status: "Stopped", pid: null });
  if (cleanup.killedPids.length) {
    await emitLog(serviceId, "warning", `Stopped child/orphan process IDs: ${cleanup.killedPids.join(", ")}`);
  }
  await publishLastExecutionStatus({
    title: `${SERVICE_DEFINITIONS[serviceId].label} stopped`,
    category: "Service command",
    message: `${SERVICE_DEFINITIONS[serviceId].label} stopped successfully.`,
    source: serviceId
  });
  return { serviceId, ok: true, killedPids: cleanup.killedPids };
}

async function handleOutput(serviceId, level, chunk) {
  const text = chunk.toString();
  const lines = text.split(/\r?\n/).filter(Boolean);
  for (const line of lines) {
    const outputLevel = normalizeOutputLevel(level, line);

    if (serviceId === "intent" || String(line).startsWith("[intent]")) {
      rememberPendingSuccessfulAiActionFromIntentLine(line);
    }

    await emitLog(serviceId, outputLevel, line);
    let aiActionPublished = false;
    const task = await inferTaskFromLog(serviceId, line);
    if (task) {
      broadcast({ type: "task", task });
      const aiActionFromTask = inferSuccessfulAiActionFromTask(task);
      if (aiActionFromTask) {
        await publishLastSuccessfulAiAction(aiActionFromTask);
        aiActionPublished = true;
      }
    }

    if (outputLevel !== "error") {
      if (isSpeakerPlaybackSuccess(line)) {
        const semanticAction = await consumePendingSuccessfulAiAction() || await inferLatestSuccessfulAiActionFromIntentLog();
        if (semanticAction) {
          await publishLastSuccessfulAiAction(semanticAction);
        }
        continue;
      }

      if (!aiActionPublished) {
        const aiAction = inferSuccessfulAiActionFromLog(serviceId, line);
        if (aiAction) {
          await publishLastSuccessfulAiAction(aiAction);
          continue;
        }
      }

      const executionStatus = inferExecutionStatusFromLog(serviceId, line);
      if (executionStatus) {
        await publishLastExecutionStatus(executionStatus);
      }
    }
  }
}

function normalizeOutputLevel(level, line) {
  if (level !== "error") return level;
  const text = String(line || "");
  if (/"\w+\s+\/[^"]*\s+HTTP\/1\.1"\s+200\s+-/i.test(text)) {
    return "info";
  }
  return level;
}

async function handleProcessError(serviceId, error) {
  updateService(serviceId, { running: false, status: "Error" });
  await emitLog(serviceId, "error", error.message);
}

async function handleExit(serviceId, code, signal) {
  processes.delete(serviceId);
  const intentionalStop = stoppingServices.delete(serviceId) || signal === "SIGTERM";
  const crashed = !intentionalStop && code !== 0;
  updateService(serviceId, {
    running: false,
    status: crashed ? "Crashed" : "Stopped",
    pid: null,
    lastExitCode: code
  });
  await emitLog(serviceId, crashed ? "error" : "warning", `Exited with code ${code ?? "none"} signal ${signal ?? "none"}`);
  if (!crashed && code === 0) {
    await publishLastExecutionStatus({
      title: `${SERVICE_DEFINITIONS[serviceId].label} completed`,
      category: "Service command",
      message: `${SERVICE_DEFINITIONS[serviceId].label} exited successfully.`,
      source: serviceId
    });
  }
  if (crashed) {
    const task = await addTask({
      name: `${SERVICE_DEFINITIONS[serviceId].label} crashed`,
      type: "Service",
      status: "Failed",
      details: `Exit code ${code ?? "none"}, signal ${signal ?? "none"}`
    });
    broadcast({ type: "task", task });
  }
}

async function publishLastSuccessfulAiAction(action) {
  const next = await updateLastSuccessfulAiAction(action);
  broadcast({ type: "last-successful-ai-action", action: next });
  await emitLog("intent", "info", `AI Success: ${next.title} - ${next.message}`);
  return next;
}

async function publishLastExecutionStatus(status) {
  const next = await updateLastExecutionStatus(status);
  broadcast({ type: "last-execution-status", status: next });
  await emitLog("intent", "info", `Execution Success: ${next.title} - ${next.message}`);
  return next;
}

function updateService(serviceId, patch) {
  const current = serviceState.get(serviceId);
  serviceState.set(serviceId, { ...current, ...patch });
  broadcast({ type: "status", status: getStatus() });
}

async function emitLog(serviceId, level, message) {
  const def = SERVICE_DEFINITIONS[serviceId] || SERVICE_DEFINITIONS.intent;
  const entry = await appendLog({
    service: serviceId,
    serviceLabel: def.label,
    tab: level === "error" ? "errors" : def.logTab,
    level,
    message: String(message)
  });
  broadcast({ type: "log", log: entry });
  if (level === "error") {
    broadcast({ type: "error", log: entry });
  }
}

function replaceTokens(value, settings) {
  if (Array.isArray(value)) {
    return value.map((item) => replaceTokens(item, settings));
  }
  return String(value)
    .replaceAll("{COM_PORT}", settings.comPort || "COM13")
    .replaceAll("{BAUD_RATE}", settings.baudRate || "115200");
}

function killProcessTree(pid) {
  return new Promise((resolve) => {
    if (!pid) return resolve();
    const killer = spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
      windowsHide: true,
      shell: false
    });
    killer.on("exit", () => resolve());
    killer.on("error", () => resolve());
  });
}

function cleanupServiceOrphans(serviceId) {
  const cleanup = ORPHAN_CLEANUP[serviceId];
  if (!cleanup || process.platform !== "win32") {
    return Promise.resolve({ killedPids: [] });
  }

  const script = `
$ErrorActionPreference = "SilentlyContinue"
$ports = @(${cleanup.ports.map((port) => Number(port)).join(",")})
$patterns = @(${cleanup.patterns.map((pattern) => JSON.stringify(pattern)).join(",")})
$found = New-Object System.Collections.Generic.HashSet[int]
foreach ($port in $ports) {
  if ($null -eq $port) { continue }
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { [void]$found.Add([int]$_.OwningProcess) }
}
Get-CimInstance Win32_Process |
  Where-Object {
    $cmd = $_.CommandLine
    if (-not $cmd -or $_.ProcessId -eq $PID) { return $false }
    foreach ($pattern in $patterns) {
      if ($cmd -like $pattern) { return $true }
    }
    return $false
  } |
  ForEach-Object { [void]$found.Add([int]$_.ProcessId) }
$ownPid = $PID
$parentPid = (Get-CimInstance Win32_Process -Filter "ProcessId=$ownPid").ParentProcessId
@($found) |
  Where-Object { $_ -and $_ -ne $ownPid -and $_ -ne $parentPid } |
  Sort-Object -Unique |
  ForEach-Object {
    taskkill /PID $_ /T /F | Out-Null
    Write-Output $_
  }
`;

  return new Promise((resolve) => {
    const encoded = Buffer.from(script, "utf16le").toString("base64");
    const child = spawn("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded], {
      windowsHide: true,
      shell: false
    });

    let output = "";
    child.stdout.on("data", (chunk) => {
      output += chunk.toString();
    });
    child.on("exit", () => {
      const killedPids = output
        .split(/\r?\n/)
        .map((line) => Number(line.trim()))
        .filter((pid) => Number.isInteger(pid) && pid > 0);
      resolve({ killedPids: [...new Set(killedPids)] });
    });
    child.on("error", () => resolve({ killedPids: [] }));
  });
}
