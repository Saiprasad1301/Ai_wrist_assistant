import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  Archive,
  CheckCircle2,
  ClipboardList,
  Cloud,
  Copy,
  Cpu,
  Database,
  Download,
  Folder,
  Gauge,
  Globe2,
  HardDrive,
  Maximize2,
  Menu,
  Mic,
  Network,
  Package,
  Play,
  Puzzle,
  RefreshCw,
  Router,
  Save,
  Server,
  Settings,
  Square,
  Terminal,
  Trash2,
  UploadCloud,
  UserCircle,
  Wifi,
  X,
  Zap
} from "lucide-react";
import "./styles.css";

const API_BASE = "http://127.0.0.1:8787";
const WS_URL = "ws://127.0.0.1:8787/ws";

const pageLabels = {
  dashboard: "Dashboard",
  logs: "Console",
  tasks: "Activity",
  settings: "Settings"
};

const logTabs = [
  { id: "esp32", label: "ESP32 Logs" },
  { id: "n8n", label: "n8n Logs" },
  { id: "mic", label: "Mic Logs" },
  { id: "workflow", label: "Workflow Logs" },
  { id: "errors", label: "Error Logs" }
];

const sidebarSections = [
  {
    items: [
      { label: "Dashboard", icon: Gauge, page: "dashboard" },
      { label: "Servers", icon: Server },
      { label: "Account", icon: UserCircle }
    ]
  },
  {
    title: "General",
    items: [
      { label: "Console", icon: Terminal, page: "logs" },
      { label: "Settings", icon: Settings, page: "settings" },
      { label: "Activity", icon: Activity, page: "tasks" }
    ]
  },
  {
    title: "Management",
    items: [
      { label: "Files", icon: Folder },
      { label: "Plugins", icon: Puzzle },
      { label: "Mods", icon: Package },
      { label: "Databases", icon: Database },
      { label: "Backups", icon: Archive },
      { label: "Importer", icon: UploadCloud },
      { label: "Network", icon: Network },
      { label: "Subdomains", icon: Globe2 }
    ]
  }
];

function App() {
  const [page, setPage] = useState("dashboard");
  const [status, setStatus] = useState(null);
  const [logs, setLogs] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [settings, setSettings] = useState(null);
  const [lastSuccessfulAiAction, setLastSuccessfulAiAction] = useState(null);
  const [lastExecutionStatus, setLastExecutionStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [wsConnected, setWsConnected] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    let socket;
    let reconnectTimer;
    let closedByApp = false;

    function connectSocket() {
      socket = new WebSocket(WS_URL);

      socket.onopen = () => {
        setWsConnected(true);
        loadInitialData();
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "log") setLogs((current) => [...current, message.log].slice(-5000));
        if (message.type === "status") setStatus(message.status);
        if (message.type === "task") loadTasks();
        if (message.type === "logs-cleared") setLogs([]);
        if (message.type === "last-successful-ai-action") setLastSuccessfulAiAction(message.action);
        if (message.type === "last-execution-status") setLastExecutionStatus(message.status);
      };
      socket.onerror = () => {
        setWsConnected(false);
        setToast("WebSocket disconnected. Backend may not be running.");
      };
      socket.onclose = () => {
        setWsConnected(false);
        if (!closedByApp) {
          reconnectTimer = window.setTimeout(connectSocket, 1500);
        }
      };
    }

    loadInitialData();
    connectSocket();

    return () => {
      closedByApp = true;
      window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  async function loadInitialData() {
    try {
      const [
        nextStatus,
        nextLogs,
        nextTasks,
        nextSettings,
        nextLastSuccessfulAiAction,
        nextLastExecutionStatus
      ] = await Promise.all([
        api("/api/status"),
        api("/api/logs"),
        api("/api/tasks"),
        api("/api/settings"),
        api("/api/last-successful-ai-action"),
        api("/api/last-execution-status")
      ]);
      setStatus(nextStatus);
      setLogs(nextLogs);
      setTasks(nextTasks);
      setSettings(nextSettings);
      setLastSuccessfulAiAction(nextLastSuccessfulAiAction);
      setLastExecutionStatus(nextLastExecutionStatus);
    } catch (error) {
      setToast(error.message);
    }
  }

  async function loadTasks() {
    setTasks(await api("/api/tasks"));
  }

  async function runAction(path, label) {
    setBusy(true);
    try {
      const result = await api(path, { method: "POST" });
      setStatus(result.status || (await api("/api/status")));
      setToast(label);
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(false);
    }
  }

  function navigate(nextPage) {
    if (!nextPage) return;
    setPage(nextPage);
    setSidebarOpen(false);
  }

  return (
    <div className="min-h-screen bg-dashboard text-slate-100">
      <Sidebar page={page} navigate={navigate} open={sidebarOpen} setOpen={setSidebarOpen} />

      <main className="min-h-screen lg:pl-[280px]">
        <TopHeader
          busy={busy}
          currentPage={pageLabels[page]}
          runAction={runAction}
          setSidebarOpen={setSidebarOpen}
          wsConnected={wsConnected}
        />

        {toast && (
          <div className="mx-4 mt-4 rounded-lg border border-violet-400/30 bg-violet-500/10 px-4 py-3 text-sm text-violet-100 shadow-lg shadow-violet-950/20 lg:mx-8">
            {toast}
          </div>
        )}

        <section className="space-y-6 p-4 lg:p-8">
          {page === "dashboard" && (
            <Dashboard
              busy={busy}
              logs={logs}
              lastExecutionStatus={lastExecutionStatus}
              lastSuccessfulAiAction={lastSuccessfulAiAction}
              runAction={runAction}
              setLogs={setLogs}
              status={status}
              tasks={tasks}
              wsConnected={wsConnected}
            />
          )}
          {page === "logs" && (
            <LogsPage logs={logs} setLogs={setLogs} status={status} tasks={tasks} wsConnected={wsConnected} />
          )}
          {page === "tasks" && <TasksPage tasks={tasks} reload={loadTasks} />}
          {page === "settings" && settings && <SettingsPage settings={settings} setSettings={setSettings} />}
        </section>
      </main>
    </div>
  );
}

function Sidebar({ page, navigate, open, setOpen }) {
  return (
    <>
      <button className="mobile-scrim" aria-label="Close sidebar" onClick={() => setOpen(false)} data-open={open} />
      <aside className={`sidebar-shell ${open ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}>
        <div className="flex items-center gap-3 px-4 py-5">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-violet-500/15 text-violet-200 shadow-lg shadow-violet-950/40">
            <Router size={22} />
          </div>
          <div>
            <div className="text-xs font-medium uppercase tracking-[0.25em] text-slate-500">Local Cloud</div>
            <h1 className="text-lg font-semibold text-white">AI Wrist</h1>
          </div>
        </div>

        <nav className="mt-3 space-y-6 px-3">
          {sidebarSections.map((section, index) => (
            <div key={section.title || index}>
              {section.title && <div className="sidebar-section-title">{section.title}</div>}
              <div className="space-y-1">
                {section.items.map((item) => {
                  const Icon = item.icon;
                  const active = item.page === page;
                  return (
                    <button
                      key={item.label}
                      className={`sidebar-item ${active ? "sidebar-item-active" : ""} ${!item.page ? "opacity-70" : ""}`}
                      onClick={() => navigate(item.page)}
                      type="button"
                    >
                      <Icon size={19} />
                      <span>{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </aside>
    </>
  );
}

function TopHeader({ busy, currentPage, runAction, setSidebarOpen, wsConnected }) {
  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-[#080d22]/90 px-4 py-4 shadow-xl shadow-black/10 backdrop-blur-xl lg:px-8">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex items-center gap-4">
          <button className="icon-button lg:hidden" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar">
            <Menu size={19} />
          </button>
          <div>
            <p className="text-sm font-medium text-slate-400">Windows local dashboard</p>
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-2xl font-semibold tracking-normal text-white">Dashboard</h2>
              <span className="rounded-full border border-violet-400/30 bg-violet-500/10 px-3 py-1 text-xs font-semibold text-violet-100">
                {currentPage}
              </span>
              <span className={`live-dot ${wsConnected ? "bg-emerald-400" : "bg-slate-500"}`} />
            </div>
          </div>
        </div>
        <ActionBar busy={busy} runAction={runAction} />
      </div>
    </header>
  );
}

function ActionBar({ busy, runAction }) {
  return (
    <div className="flex flex-wrap gap-2">
      <button disabled={busy} onClick={() => runAction("/api/start", "Start command sent")} className="btn-primary">
        <Play size={16} /> Start All
      </button>
      <button disabled={busy} onClick={() => runAction("/api/stop", "Stop command sent")} className="btn-muted">
        <Square size={16} /> Stop All
      </button>
      <button disabled={busy} onClick={() => runAction("/api/restart", "Restart command sent")} className="btn-muted">
        <RefreshCw size={16} /> Restart All
      </button>
    </div>
  );
}

function Dashboard({
  status,
  logs,
  tasks,
  runAction,
  busy,
  setLogs,
  wsConnected,
  lastSuccessfulAiAction,
  lastExecutionStatus
}) {
  const services = status?.services || {};
  const cards = [
    { id: "esp32", title: "ESP32 Serial", icon: Wifi, active: "Connected", inactive: "Disconnected" },
    { id: "n8n", title: "n8n Server", icon: Server, active: "Running", inactive: "Stopped" },
    { id: "stt", title: "Mic/STT", icon: Mic, active: "Active", inactive: "Inactive" },
    { id: "intent", title: "Workflow", icon: Activity, active: "Ready", inactive: "Error" }
  ];

  return (
    <>
      <CloudStats logs={logs} status={status} tasks={tasks} wsConnected={wsConnected} />
      <div className="grid gap-4 xl:grid-cols-2">
        <LastSuccessfulAiAction action={lastSuccessfulAiAction} />
        <LastExecutionStatus status={lastExecutionStatus} />
      </div>
      <ConsolePanel logs={logs} setLogs={setLogs} title="Live Console" />

      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
        {cards.map((card) => (
          <StatusCard key={card.id} {...card} service={services[card.id]} />
        ))}
      </div>

      <ServiceControls busy={busy} runAction={runAction} services={services} status={status} />

      <section className="panel">
        <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="eyebrow">Assistant activity</p>
            <h3 className="section-title">Latest Tasks</h3>
          </div>
          <span className="text-sm text-slate-500">{tasks.length} total records</span>
        </div>
        <TaskTable tasks={tasks.slice(0, 6)} compact />
      </section>
    </>
  );
}

function LastSuccessfulAiAction({ action }) {
  return (
    <LastSuccessCard
      emptyPrimary="No successful AI action yet"
      emptySecondary="Waiting for assistant activity"
      icon={CheckCircle2}
      item={action}
      label="User-facing result"
      title="Last Successful AI Action"
    />
  );
}

function LastExecutionStatus({ status }) {
  return (
    <LastSuccessCard
      emptyPrimary="No execution status yet"
      emptySecondary="Waiting for workflow or terminal activity"
      icon={Terminal}
      item={status}
      label="Technical execution"
      title="Last Execution Status"
    />
  );
}

function LastSuccessCard({ item, title, label, emptyPrimary, emptySecondary, icon: Icon }) {
  return (
    <section className="success-card">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="success-icon">
            <Icon size={21} />
          </div>
          <div>
            <p className="eyebrow">{label}</p>
            <h3 className="section-title text-lg">{title}</h3>
          </div>
        </div>
        {item && <span className="badge badge-live">{item.status || "Success"}</span>}
      </div>

      {item ? (
        <div className="mt-5 space-y-3">
          <div>
            <div className="text-lg font-semibold text-white">{item.title}</div>
            <div className="mt-1 text-sm font-medium text-cyan-200">{item.category}</div>
          </div>
          <p className="text-sm leading-6 text-slate-300">{item.message}</p>
          <div className="text-xs font-medium text-slate-500">{formatTimestamp(item.timestamp)}</div>
        </div>
      ) : (
        <div className="mt-6 rounded-xl border border-dashed border-white/10 bg-[#090d22]/60 p-5">
          <div className="font-semibold text-slate-300">{emptyPrimary}</div>
          <div className="mt-1 text-sm text-slate-600">{emptySecondary}</div>
        </div>
      )}
    </section>
  );
}

function CloudStats({ status, logs, tasks, wsConnected }) {
  const services = Object.values(status?.services || {});
  const runningCount = services.filter((service) => service.running).length;
  const completedTasks = tasks.filter((task) => task.status === "Completed").length;
  const failedTasks = tasks.filter((task) => task.status === "Failed").length;

  const stats = [
    {
      label: "CPU Usage:",
      value: status ? `${runningCount} Active / ${services.length || 5} Services` : "Offline / 50%",
      icon: Cpu
    },
    {
      label: "Memory Usage:",
      value: `${logs.length} Logs / 5000 Buffer`,
      icon: Server
    },
    {
      label: "Disk Usage:",
      value: `${tasks.length} Tasks / Local JSON`,
      icon: HardDrive
    },
    {
      label: "Inbound / Outbound:",
      value: wsConnected ? `Live WS / ${completedTasks} Done` : `Offline / ${failedTasks} Failed`,
      icon: Cloud
    }
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
      {stats.map((item) => {
        const Icon = item.icon;
        return (
          <div key={item.label} className="stat-card">
            <div>
              <div className="text-sm font-medium text-slate-500">{item.label}</div>
              <div className="mt-1 text-base font-semibold text-slate-200">{item.value}</div>
            </div>
            <div className="stat-icon">
              <Icon size={27} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ConsolePanel({ logs, setLogs, title = "Console", showCategoryTabs = false }) {
  const [mode, setMode] = useState("all");
  const [category, setCategory] = useState("all");
  const [service, setService] = useState("");
  const [fullscreen, setFullscreen] = useState(false);
  const listRef = useRef(null);

  const filtered = useMemo(() => {
    return logs.filter((log) => {
      if (mode === "info" && log.level === "error") return false;
      if (category !== "all" && log.tab !== category) return false;
      if (service && log.service !== service) return false;
      return true;
    });
  }, [category, logs, mode, service]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [filtered.length]);

  async function clear() {
    await api("/api/logs", { method: "DELETE" });
    setLogs([]);
  }

  function download() {
    const blob = new Blob([formatLogs(filtered)], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `assistant-${category}-logs.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function copy() {
    await navigator.clipboard?.writeText(formatLogs(filtered));
  }

  return (
    <section className={`console-panel ${fullscreen ? "console-fullscreen" : ""}`}>
      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <p className="eyebrow">Runtime output</p>
          <h3 className="section-title">{title}</h3>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button className={`console-tab ${mode === "all" ? "console-tab-active" : ""}`} onClick={() => setMode("all")} type="button">
            View All ({logs.length || 0})
          </button>
          <button className={`console-tab ${mode === "info" ? "console-tab-active" : ""}`} onClick={() => setMode("info")} type="button">
            Info ({logs.filter((log) => log.level !== "error").length || 0})
          </button>
          {showCategoryTabs && (
            <select value={category} onChange={(event) => setCategory(event.target.value)} className="input max-w-44">
              <option value="all">All log tabs</option>
              {logTabs.map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </select>
          )}
          {showCategoryTabs && (
            <select value={service} onChange={(event) => setService(event.target.value)} className="input max-w-40">
              <option value="">All services</option>
              <option value="esp32">ESP32</option>
              <option value="n8n">n8n</option>
              <option value="stt">Mic/STT</option>
              <option value="intent">Intent</option>
              <option value="tts">TTS</option>
            </select>
          )}
          <button className="icon-button" onClick={clear} type="button" title="Clear logs">
            <Trash2 size={16} />
          </button>
          <button className="icon-button" onClick={copy} type="button" title="Copy logs">
            <Copy size={16} />
          </button>
          <button className="icon-button" onClick={download} type="button" title="Download logs">
            <Download size={16} />
          </button>
          <button className="icon-button" onClick={() => setFullscreen((value) => !value)} type="button" title="Fullscreen">
            {fullscreen ? <X size={16} /> : <Maximize2 size={16} />}
          </button>
        </div>
      </div>

      {showCategoryTabs && (
        <div className="mb-3 flex flex-wrap gap-2">
          <button className={`tab ${category === "all" ? "tab-active" : ""}`} onClick={() => setCategory("all")} type="button">All Logs</button>
          {logTabs.map((item) => (
            <button key={item.id} onClick={() => setCategory(item.id)} className={`tab ${category === item.id ? "tab-active" : ""}`} type="button">
              {item.label}
            </button>
          ))}
        </div>
      )}

      <div ref={listRef} className="console-scroll">
        {filtered.length === 0 && <div className="text-slate-600">Waiting for logs...</div>}
        {filtered.slice(-700).map((log) => (
          <div key={log.id} className={`log-line ${levelClass(log.level)}`}>
            <span className="text-slate-500">[{labelForLevel(log.level)}]</span>{" "}
            <span className="text-violet-300">{new Date(log.timestamp).toLocaleTimeString()}</span>{" "}
            <span className="text-cyan-300">{log.serviceLabel || log.service}</span>{" "}
            <span>{log.message}</span>
          </div>
        ))}
      </div>

      <form className="console-command" onSubmit={(event) => event.preventDefault()}>
        <Zap size={16} />
        <input aria-label="Command input" placeholder="Type a command..." />
      </form>
    </section>
  );
}

function LogsPage({ logs, setLogs, status, tasks, wsConnected }) {
  return (
    <div className="space-y-5">
      <CloudStats logs={logs} status={status} tasks={tasks} wsConnected={wsConnected} />
      <ConsolePanel logs={logs} setLogs={setLogs} showCategoryTabs title="Live Logs" />
    </div>
  );
}

function ServiceControls({ services, runAction, busy, status }) {
  return (
    <section className="panel">
      <div className="mb-5 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow">Process manager</p>
          <h3 className="section-title">Service Controls</h3>
        </div>
        <span className="text-sm text-slate-500">
          {status?.timestamp ? `Last update ${new Date(status.timestamp).toLocaleTimeString()}` : "Waiting for service state"}
        </span>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {Object.values(services).map((service) => (
          <div key={service.id} className="service-card">
            <div className="flex min-w-0 items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <div className="mini-icon"><Server size={17} /></div>
                  <div className="truncate font-semibold text-white">{service.label}</div>
                </div>
                <div className="mt-3 grid gap-1 text-sm text-slate-500">
                  <span>PID: <span className="text-slate-300">{service.pid || "none"}</span></span>
                  <span>Started: <span className="text-slate-300">{service.startedAt ? new Date(service.startedAt).toLocaleTimeString() : "not running"}</span></span>
                </div>
              </div>
              <StatusBadge service={service}>{service.status}</StatusBadge>
            </div>
            <div className="mt-5 flex gap-2">
              <button disabled={busy} className="btn-small" onClick={() => runAction(`/api/services/${service.id}/start`, `${service.label} start sent`)}>
                Start
              </button>
              <button disabled={busy} className="btn-small-muted" onClick={() => runAction(`/api/services/${service.id}/stop`, `${service.label} stop sent`)}>
                Stop
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function StatusCard({ title, icon: Icon, active, inactive, service }) {
  const running = Boolean(service?.running);
  const display = running ? active : inactive;

  return (
    <div className="status-card">
      <div className="flex items-start justify-between gap-4">
        <div className={`status-icon ${running ? "status-icon-live" : ""}`}>
          <Icon size={22} />
        </div>
        <StatusBadge service={service} fallback={display}>{display}</StatusBadge>
      </div>
      <div className="mt-5">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <p className="mt-1 text-sm text-slate-500">{service?.status || "Stopped"}</p>
      </div>
    </div>
  );
}

function TasksPage({ tasks, reload }) {
  const [form, setForm] = useState({ name: "", type: "General", status: "Created" });

  async function addManualTask(event) {
    event.preventDefault();
    await api("/api/tasks", { method: "POST", body: JSON.stringify(form) });
    setForm({ name: "", type: "General", status: "Created" });
    reload();
  }

  return (
    <div className="space-y-5">
      <form onSubmit={addManualTask} className="panel grid gap-3 md:grid-cols-[1fr_180px_180px_auto]">
        <input className="input" placeholder="Task name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        <input className="input" placeholder="Type" value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value })} />
        <select className="input" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
          <option>Created</option>
          <option>Running</option>
          <option>Completed</option>
          <option>Failed</option>
        </select>
        <button className="btn-primary">Add Task</button>
      </form>
      <section className="panel">
        <div className="mb-4">
          <p className="eyebrow">Assistant history</p>
          <h3 className="section-title">Task History</h3>
        </div>
        <TaskTable tasks={tasks} />
      </section>
    </div>
  );
}

function TaskTable({ tasks, compact = false }) {
  return (
    <div className="overflow-auto">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="border-b border-white/10 text-slate-500">
          <tr>
            <th className="py-3 font-semibold">Task name</th>
            <th className="font-semibold">Type</th>
            <th className="font-semibold">Status</th>
            <th className="font-semibold">Timestamp</th>
            {!compact && <th className="font-semibold">Details</th>}
          </tr>
        </thead>
        <tbody>
          {tasks.length === 0 && (
            <tr><td colSpan={compact ? 4 : 5}><Empty text="No tasks yet." /></td></tr>
          )}
          {tasks.map((task) => (
            <tr key={task.id} className="border-b border-white/[0.06]">
              <td className="py-3 font-medium text-white">{task.name}</td>
              <td className="text-slate-300">{task.type}</td>
              <td><TaskStatus status={task.status} /></td>
              <td className="text-slate-500">{new Date(task.timestamp).toLocaleString()}</td>
              {!compact && <td className="max-w-sm truncate text-slate-500">{task.details}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SettingsPage({ settings, setSettings }) {
  const [draft, setDraft] = useState(settings);
  const serviceIds = Object.keys(draft.commands || {});

  async function save(event) {
    event.preventDefault();
    const saved = await api("/api/settings", { method: "PUT", body: JSON.stringify(draft) });
    setSettings(saved);
  }

  function updateCommand(serviceId, field, value) {
    setDraft({
      ...draft,
      commands: {
        ...draft.commands,
        [serviceId]: {
          ...draft.commands[serviceId],
          [field]: field === "args" ? value.split("\n").filter(Boolean) : value
        }
      }
    });
  }

  return (
    <form onSubmit={save} className="space-y-5">
      <section className="panel">
        <div className="mb-4">
          <p className="eyebrow">Serial monitor</p>
          <h3 className="section-title">Serial Settings</h3>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="field">COM port<input className="input" value={draft.comPort} onChange={(event) => setDraft({ ...draft, comPort: event.target.value })} /></label>
          <label className="field">Baud rate<input className="input" value={draft.baudRate} onChange={(event) => setDraft({ ...draft, baudRate: event.target.value })} /></label>
        </div>
      </section>

      <section className="panel">
        <div className="mb-4">
          <p className="eyebrow">Windows process commands</p>
          <h3 className="section-title">Commands</h3>
        </div>
        <div className="space-y-4">
          {serviceIds.map((serviceId) => {
            const command = draft.commands[serviceId];
            return (
              <div key={serviceId} className="rounded-xl border border-white/10 bg-[#0b1026]/70 p-4 shadow-lg shadow-black/10">
                <div className="mb-3 flex items-center justify-between">
                  <h4 className="font-semibold uppercase tracking-wide text-slate-300">{serviceId}</h4>
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <input type="checkbox" checked={command.enabled !== false} onChange={(event) => updateCommand(serviceId, "enabled", event.target.checked)} />
                    Enabled
                  </label>
                </div>
                <div className="grid gap-3 lg:grid-cols-2">
                  <label className="field">Command<input className="input" value={command.command} onChange={(event) => updateCommand(serviceId, "command", event.target.value)} /></label>
                  <label className="field">Working folder<input className="input" value={command.cwd || ""} onChange={(event) => updateCommand(serviceId, "cwd", event.target.value)} /></label>
                  <label className="field lg:col-span-2">Arguments, one per line<textarea className="input min-h-28" value={(command.args || []).join("\n")} onChange={(event) => updateCommand(serviceId, "args", event.target.value)} /></label>
                </div>
              </div>
            );
          })}
        </div>
        <button className="btn-primary mt-5"><Save size={16} /> Save Settings</button>
      </section>
    </form>
  );
}

function StatusBadge({ service, children, fallback }) {
  const running = Boolean(service?.running);
  const hasError = isServiceError(service);
  const className = hasError
    ? "badge badge-error"
    : running
      ? "badge badge-live"
      : "badge badge-muted";
  return <span className={className}>{children || fallback || service?.status || "Stopped"}</span>;
}

function TaskStatus({ status }) {
  const styles = {
    Completed: "badge-live",
    Running: "badge-info",
    Failed: "badge-error",
    Created: "badge-muted"
  };
  return <span className={`badge ${styles[status] || styles.Created}`}>{status}</span>;
}

function Empty({ text }) {
  return <div className="py-8 text-center text-sm text-slate-600">{text}</div>;
}

function isServiceError(service) {
  if (!service) return false;
  const status = String(service.status || "").toLowerCase();
  return status.includes("crash") || status.includes("error") || status.includes("failed") || service.lastExitCode > 0;
}

function levelClass(level) {
  if (level === "error") return "text-red-300";
  if (level === "warning") return "text-amber-200";
  return "text-slate-300";
}

function labelForLevel(level) {
  if (level === "error") return "ERROR";
  if (level === "warning") return "WARN";
  return "INFO";
}

function formatLogs(items) {
  return items.map((log) => `[${log.timestamp}] ${log.serviceLabel || log.service}: ${log.message}`).join("\n");
}

function formatTimestamp(timestamp) {
  if (!timestamp) return "Timestamp unavailable";
  return new Date(timestamp).toLocaleString();
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

createRoot(document.getElementById("root")).render(<App />);
