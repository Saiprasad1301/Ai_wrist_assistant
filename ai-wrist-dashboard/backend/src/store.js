import crypto from "node:crypto";
import fs from "node:fs/promises";
import {
  INTENT_SERVICE_LOG_PATH,
  LAST_EXECUTION_STATUS_PATH,
  LAST_SUCCESSFUL_AI_ACTION_PATH,
  LOGS_PATH,
  TASKS_PATH,
  readJson,
  writeJson
} from "./config.js";

const MAX_LOGS = 5000;

let logs = [];
let tasks = [];
let lastSuccessfulAiAction = null;
let lastExecutionStatus = null;
let pendingSuccessfulAiAction = null;

export async function loadStore() {
  logs = await readJson(LOGS_PATH, []);
  tasks = await readJson(TASKS_PATH, []);
  lastSuccessfulAiAction = await readJson(LAST_SUCCESSFUL_AI_ACTION_PATH, null);
  lastExecutionStatus = await readJson(LAST_EXECUTION_STATUS_PATH, null);
  if (isGenericPlaybackAction(lastSuccessfulAiAction)) {
    const semanticAction = await inferLatestSuccessfulAiActionFromIntentLog();
    if (semanticAction) {
      lastSuccessfulAiAction = buildSuccessRecord(semanticAction);
      await writeJson(LAST_SUCCESSFUL_AI_ACTION_PATH, lastSuccessfulAiAction);
      return;
    }
  }
  await backfillLastSuccessfulAiActionFromLogs();
}

export function getLogs(filter = {}) {
  const { service, level, tab } = filter;
  return logs.filter((entry) => {
    if (service && entry.service !== service) return false;
    if (level && entry.level !== level) return false;
    if (tab && entry.tab !== tab) return false;
    return true;
  });
}

export async function clearLogs() {
  logs = [];
  await writeJson(LOGS_PATH, logs);
}

export async function appendLog(entry) {
  const next = {
    id: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
    level: "info",
    tab: "workflow",
    ...entry
  };
  logs.push(next);
  if (logs.length > MAX_LOGS) {
    logs = logs.slice(logs.length - MAX_LOGS);
  }
  await writeJson(LOGS_PATH, logs);
  return next;
}

export function getTasks() {
  return tasks;
}

export async function addTask(task) {
  const next = {
    id: crypto.randomUUID(),
    name: task.name || "Assistant task",
    type: task.type || "General",
    status: task.status || "Created",
    timestamp: task.timestamp || new Date().toISOString(),
    details: task.details || ""
  };
  tasks.unshift(next);
  await writeJson(TASKS_PATH, tasks);
  return next;
}

export async function updateTask(id, patch) {
  tasks = tasks.map((task) => (task.id === id ? { ...task, ...patch } : task));
  await writeJson(TASKS_PATH, tasks);
  return tasks.find((task) => task.id === id);
}

export async function inferTaskFromLog(service, text) {
  const normalized = String(text || "").toLowerCase();
  if (isBenignDiagnosticLine(normalized)) {
    return null;
  }
  if (normalized.includes("email sent")) {
    return addTask({ name: "Email sent", type: "Email", status: "Completed", details: text });
  }
  if (normalized.includes("reminder created") || normalized.includes("reminder set")) {
    return addTask({ name: "Reminder created", type: "Reminder", status: "Completed", details: text });
  }
  if (normalized.includes("wake word detected")) {
    return addTask({ name: "Voice command session", type: "Voice", status: "Running", details: text });
  }
  if (normalized.includes("upload failed") || normalized.includes("failed")) {
    return addTask({ name: `${service} error`, type: "Error", status: "Failed", details: text });
  }
  return null;
}

export function getLastSuccessfulAiAction() {
  return lastSuccessfulAiAction;
}

export function getLastExecutionStatus() {
  return lastExecutionStatus;
}

export async function updateLastSuccessfulAiAction(action) {
  lastSuccessfulAiAction = buildSuccessRecord(action);
  await writeJson(LAST_SUCCESSFUL_AI_ACTION_PATH, lastSuccessfulAiAction);
  return lastSuccessfulAiAction;
}

export async function updateLastExecutionStatus(status) {
  lastExecutionStatus = buildSuccessRecord(status);
  await writeJson(LAST_EXECUTION_STATUS_PATH, lastExecutionStatus);
  return lastExecutionStatus;
}

export function inferSuccessfulAiActionFromTask(task) {
  if (!task || task.status !== "Completed") return null;

  const type = String(task.type || "").toLowerCase();
  const name = String(task.name || "").toLowerCase();
  const details = task.details || task.name || "";

  if (type.includes("email") || name.includes("email sent")) {
    return {
      title: "Email sent",
      category: "Email",
      message: cleanMessage(details, "Sent email successfully."),
      source: "task"
    };
  }

  if (type.includes("reminder") || name.includes("reminder")) {
    return {
      title: "Reminder created",
      category: "Reminder",
      message: cleanMessage(details, "Created reminder successfully."),
      source: "task"
    };
  }

  if (type.includes("calendar") || name.includes("calendar") || name.includes("event created")) {
    return {
      title: "Calendar event created",
      category: "Calendar",
      message: cleanMessage(details, "Created calendar event successfully."),
      source: "task"
    };
  }

  if (type.includes("question") || type.includes("llm") || name.includes("answered")) {
    return {
      title: "LLM answered a question",
      category: "LLM",
      message: cleanMessage(details, "Answered user question successfully."),
      source: "task"
    };
  }

  if (type.includes("message") || name.includes("message generated")) {
    return {
      title: "Message generated",
      category: "Message",
      message: cleanMessage(details, "Generated message successfully."),
      source: "task"
    };
  }

  return null;
}

export function inferSuccessfulAiActionFromLog(service, text) {
  const normalized = String(text || "").toLowerCase();
  const message = cleanMessage(text);

  if (normalized.includes("email sent") || normalized.includes("sent email successfully")) {
    return {
      title: "Email sent",
      category: "Email",
      message,
      source: service
    };
  }

  if (
    normalized.includes("calendar reminder created") ||
    normalized.includes("calendar event created") ||
    normalized.includes("event created") ||
    normalized.includes("reminder created") ||
    normalized.includes("reminder set")
  ) {
    return {
      title: normalized.includes("calendar") || normalized.includes("event") ? "Calendar event created" : "Reminder created",
      category: normalized.includes("calendar") || normalized.includes("event") ? "Calendar" : "Reminder",
      message,
      source: service
    };
  }

  if (
    normalized.includes("llm answered") ||
    normalized.includes("answered question") ||
    normalized.includes("question answered") ||
    normalized.includes("assistant response generated") ||
    normalized.includes("message generated") ||
    normalized.includes("user request completed")
  ) {
    return {
      title: normalized.includes("message") ? "Message generated" : "LLM answered a question",
      category: normalized.includes("message") ? "Message" : "LLM",
      message,
      source: service
    };
  }

  return null;
}

export function inferExecutionStatusFromLog(service, text) {
  const normalized = String(text || "").toLowerCase();
  const message = cleanMessage(text);

  if (isUserFacingAiSuccess(normalized)) return null;

  if (
    normalized.includes("workflow completed") ||
    normalized.includes("workflow finished") ||
    normalized.includes("execution completed") ||
    normalized.includes("automation completed") ||
    normalized.includes("automation finished")
  ) {
    return {
      title: "Workflow completed",
      category: "Workflow",
      message,
      source: service
    };
  }

  if (
    normalized.includes("script completed") ||
    normalized.includes("command completed") ||
    normalized.includes("terminal command executed") ||
    normalized.includes("backend task completed")
  ) {
    return {
      title: "Command completed",
      category: "Terminal",
      message,
      source: service
    };
  }

  if (normalized.includes("audio response was returned") || normalized.includes("command reached n8n")) {
    return {
      title: "Workflow completed",
      category: "Workflow",
      message,
      source: service
    };
  }

  return null;
}

export function isSpeakerPlaybackSuccess(text) {
  const normalized = String(text || "").toLowerCase();
  return (
    normalized.includes("speaker playback finished") ||
    normalized.includes("audio playback finished") ||
    normalized.includes("speaker output finished")
  );
}

export async function inferLatestSuccessfulAiActionFromIntentLog() {
  let raw = "";
  try {
    raw = await fs.readFile(INTENT_SERVICE_LOG_PATH, "utf8");
  } catch {
    return null;
  }

  const lines = raw.split(/\r?\n/).filter(Boolean).slice(-300);
  for (const line of [...lines].reverse()) {
    const action = semanticActionFromIntentLogLine(line);
    if (action) return action;
  }

  return null;
}

export function rememberPendingSuccessfulAiActionFromIntentLine(line) {
  const action = semanticActionFromIntentLogLine(line);
  if (!action) return null;
  pendingSuccessfulAiAction = action;
  return action;
}

export async function consumePendingSuccessfulAiAction() {
  const pending = pendingSuccessfulAiAction;
  pendingSuccessfulAiAction = null;
  return pending || inferLatestSuccessfulAiActionFromIntentLog();
}

function buildSuccessRecord(record) {
  return {
    id: crypto.randomUUID(),
    title: record.title || "Successful action",
    category: record.category || "General",
    message: cleanMessage(record.message, "Completed successfully."),
    timestamp: record.timestamp || new Date().toISOString(),
    status: "Success",
    source: record.source || "dashboard"
  };
}

function isUserFacingAiSuccess(normalized) {
  return (
    normalized.includes("email sent") ||
    normalized.includes("sent email successfully") ||
    normalized.includes("calendar reminder created") ||
    normalized.includes("calendar event created") ||
    normalized.includes("event created") ||
    normalized.includes("reminder created") ||
    normalized.includes("reminder set") ||
    normalized.includes("llm answered") ||
    normalized.includes("answered question") ||
    normalized.includes("question answered") ||
    normalized.includes("assistant response generated") ||
    normalized.includes("message generated") ||
    normalized.includes("user request completed")
  );
}

function cleanMessage(value, fallback = "Completed successfully.") {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return fallback;
  return text.length > 180 ? `${text.slice(0, 177)}...` : text;
}

async function backfillLastSuccessfulAiActionFromLogs() {
  if (lastSuccessfulAiAction) return;

  for (const entry of [...logs].reverse()) {
    if (entry.level === "error") continue;
    if (isSpeakerPlaybackSuccess(entry.message)) {
      const semanticAction = await inferLatestSuccessfulAiActionFromIntentLog();
      if (semanticAction) {
        lastSuccessfulAiAction = buildSuccessRecord({
          ...semanticAction,
          timestamp: entry.timestamp
        });
        await writeJson(LAST_SUCCESSFUL_AI_ACTION_PATH, lastSuccessfulAiAction);
        return;
      }
    }

    const action = inferSuccessfulAiActionFromLog(entry.service, entry.message);
    if (!action) continue;
    lastSuccessfulAiAction = buildSuccessRecord({
      ...action,
      timestamp: entry.timestamp
    });
    await writeJson(LAST_SUCCESSFUL_AI_ACTION_PATH, lastSuccessfulAiAction);
    return;
  }
}

function parseIntentLogEvent(line) {
  const match = String(line || "").match(/^\[intent\]\s+([^:]+):\s+(\{.*\})\s*$/);
  if (!match) return null;
  try {
    return {
      label: match[1].trim(),
      payload: JSON.parse(match[2])
    };
  } catch {
    return null;
  }
}

function semanticActionFromIntentLogLine(line) {
  const event = parseIntentLogEvent(line);
  if (!event || event.label !== "result") return null;

  const payload = event.payload;
  const transcript = cleanMessage(payload.transcript, "");
  const toolName = String(payload.tool_name || "").toLowerCase();
  const listenAgain = payload.listen_again === true || payload.listen_again === "true";

  if (listenAgain || !transcript || isNonActionTranscript(transcript)) {
    return null;
  }

  return semanticActionFromIntent(toolName, transcript);
}

function semanticActionFromIntent(toolName, transcript) {
  if (toolName === "send_email") {
    return {
      title: "Email sent",
      category: "Email",
      message: "Sent email successfully.",
      source: "intent"
    };
  }

  if (toolName === "set_reminder") {
    return {
      title: "Calendar reminder set",
      category: "Calendar",
      message: `Created reminder from: ${transcript}`,
      source: "intent"
    };
  }

  if (toolName === "respond") {
    const kind = classifyRespondIntent(transcript);
    return {
      title: kind.title,
      category: kind.category,
      message: `${kind.verb}: ${transcript}`,
      source: "intent"
    };
  }

  return null;
}

function classifyRespondIntent(transcript) {
  const normalized = String(transcript || "").toLowerCase();
  if (/\btranslate\b/.test(normalized)) {
    return { title: "Translation answered", category: "Translation", verb: "Translated request" };
  }
  if (/\bweather\b/.test(normalized)) {
    return { title: "Weather question answered", category: "Weather", verb: "Answered weather request" };
  }
  if (/\b(who|what|where|when|why|how|which|president|prime minister|barack|rahul|gandhi|modi|spell|date|time|year)\b/.test(normalized)) {
    return { title: "LLM GK answered", category: "LLM", verb: "Answered" };
  }
  return { title: "LLM answered", category: "LLM", verb: "Answered" };
}

function isNonActionTranscript(transcript) {
  const normalized = String(transcript || "").toLowerCase();
  return (
    normalized.includes("no speech was detected") ||
    normalized.includes("could not hear") ||
    normalized === "assistant"
  );
}

function isGenericPlaybackAction(action) {
  return (
    action &&
    action.title === "Assistant response delivered" &&
    String(action.message || "").toLowerCase().includes("speaker playback finished")
  );
}

function isBenignDiagnosticLine(normalized) {
  return (
    normalized.includes("failed to restore binary data id") ||
    normalized.includes("failed to start python task runner in internal mode") ||
    /"\w+\s+\/[^"]*\s+http\/1\.1"\s+200\s+-/.test(normalized)
  );
}
