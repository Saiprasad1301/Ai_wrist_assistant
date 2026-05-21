import http from "node:http";
import express from "express";
import cors from "cors";
import { ensureDataFiles } from "./config.js";
import { attachWebSocket, broadcast } from "./websocket.js";
import {
  addTask,
  clearLogs,
  getLastExecutionStatus,
  getLastSuccessfulAiAction,
  getLogs,
  getTasks,
  inferSuccessfulAiActionFromTask,
  loadStore,
  updateLastSuccessfulAiAction,
  updateTask
} from "./store.js";
import {
  getSettings,
  getStatus,
  restartAll,
  saveSettings,
  startAll,
  startService,
  stopAll,
  stopService
} from "./serviceManager.js";

const PORT = Number(process.env.DASHBOARD_API_PORT || 8787);

await ensureDataFiles();
await loadStore();

const app = express();
app.use(cors());
app.use(express.json({ limit: "1mb" }));

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, name: "AI Wrist Dashboard API", timestamp: new Date().toISOString() });
});

app.post("/api/start", async (_req, res) => {
  res.json({ results: await startAll(), status: getStatus() });
});

app.post("/api/stop", async (_req, res) => {
  res.json({ results: await stopAll(), status: getStatus() });
});

app.post("/api/restart", async (_req, res) => {
  res.json({ results: await restartAll(), status: getStatus() });
});

app.post("/api/services/:serviceId/start", async (req, res) => {
  res.json({ result: await startService(req.params.serviceId), status: getStatus() });
});

app.post("/api/services/:serviceId/stop", async (req, res) => {
  res.json({ result: await stopService(req.params.serviceId), status: getStatus() });
});

app.get("/api/status", (_req, res) => {
  res.json(getStatus());
});

app.get("/api/last-successful-ai-action", (_req, res) => {
  res.json(getLastSuccessfulAiAction());
});

app.get("/api/last-execution-status", (_req, res) => {
  res.json(getLastExecutionStatus());
});

app.get("/api/logs", (req, res) => {
  res.json(getLogs(req.query));
});

app.delete("/api/logs", async (_req, res) => {
  await clearLogs();
  broadcast({ type: "logs-cleared" });
  res.json({ ok: true });
});

app.get("/api/tasks", (_req, res) => {
  res.json(getTasks());
});

app.post("/api/tasks", async (req, res) => {
  const task = await addTask(req.body || {});
  broadcast({ type: "task", task });
  await maybeBroadcastAiActionFromTask(task);
  res.status(201).json(task);
});

app.patch("/api/tasks/:id", async (req, res) => {
  const task = await updateTask(req.params.id, req.body || {});
  if (!task) return res.status(404).json({ error: "Task not found" });
  broadcast({ type: "task", task });
  await maybeBroadcastAiActionFromTask(task);
  res.json(task);
});

app.get("/api/settings", async (_req, res) => {
  res.json(await getSettings());
});

app.put("/api/settings", async (req, res) => {
  res.json(await saveSettings(req.body || {}));
});

app.use((error, _req, res, _next) => {
  console.error(error);
  res.status(500).json({ error: error.message || "Unexpected server error" });
});

async function maybeBroadcastAiActionFromTask(task) {
  const action = inferSuccessfulAiActionFromTask(task);
  if (!action) return null;
  const saved = await updateLastSuccessfulAiAction(action);
  broadcast({ type: "last-successful-ai-action", action: saved });
  return saved;
}

const server = http.createServer(app);
attachWebSocket(server);

server.listen(PORT, () => {
  console.log(`AI Wrist Dashboard API running on http://localhost:${PORT}`);
});
