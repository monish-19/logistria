import { useEffect, useState } from "react";
import { useStore } from "./store";
import type { EventItem } from "./types";
import { AuditView, DecisionPanel, EventFeed, Header, InventoryView, NewRun, Pipeline, RoutePreview, RunSelector, SettingsDialog, Sidebar, SkeletonRows, Suppliers, SuppliersView } from "./components";
import { routeFromEvents, runLabel } from "./pipeline";

const demoEvents: EventItem[] = [
  { id: -1, run_id: "demo-run", sender: "Admin", receiver: "InventoryAgent", type: "request", payload_json: { product_name: "Sensor Module B3", quantity: 50 }, human_text: "Production run started for Sensor Module B3.", severity: "info", ts: new Date().toISOString() },
  { id: -2, run_id: "demo-run", sender: "InventoryAgent", receiver: "SupplierRankingAgent", type: "response", payload_json: { product_name: "Sensor Module B3", shortage: 3 }, human_text: "Shortage detected; ranking suppliers.", severity: "warning", ts: new Date().toISOString() },
  { id: -3, run_id: "demo-run", sender: "SupplierRankingAgent", receiver: "ProcurementAgent", type: "response", payload_json: { product_name: "Sensor Module B3", top_pick: "Apex Industrial" }, human_text: "Supplier ranking completed with Apex Industrial first.", severity: "info", ts: new Date().toISOString() },
  { id: -4, run_id: "demo-run", sender: "ProcurementAgent", receiver: "HumanApproval", type: "human_action", payload_json: { product_name: "Sensor Module B3", decision: { needs_approval: true } }, human_text: "Human approval is required before procurement.", severity: "warning", ts: new Date().toISOString() },
  { id: -5, run_id: "demo-run", sender: "Admin", receiver: "ManufacturingStep", type: "human_action", payload_json: { product_name: "Sensor Module B3", approved: true }, human_text: "Operator approved the procurement decision.", severity: "success", ts: new Date().toISOString() },
  { id: -6, run_id: "demo-run", sender: "ManufacturingStep", receiver: "LogisticsAgent", type: "decision", payload_json: { product_name: "Sensor Module B3", progress_pct: 100 }, human_text: "Manufacturing completed for Sensor Module B3.", severity: "success", ts: new Date().toISOString() },
  { id: -7, run_id: "demo-run", sender: "LogisticsAgent", receiver: "Admin", type: "response", payload_json: { product_name: "Sensor Module B3", status: "completed", route: { geometry: [[72.82, 18.96], [72.88, 19.02], [72.94, 19.08]], distance_km: 12.4, eta_minutes: 38 } }, human_text: "Logistics completed delivery; run is complete.", severity: "success", ts: new Date().toISOString() },
];

function currentView() {
  const view = window.location.hash.slice(2);
  return ["runs", "inventory", "suppliers", "audit"].includes(view) ? view : "runs";
}

export function App() {
  const { runs, events, products, approvals, inventory, suppliers, activeRun, connection, error, loading, pendingEvents, load, selectRun, connect, skipToLatest, replay } = useStore();
  const [view, setView] = useState(currentView());
  const [expanded, setExpanded] = useState(false);
  const [newRunOpen, setNewRunOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [demoEventsState, setDemoEvents] = useState<EventItem[]>([]);
  const [refreshError, setRefreshError] = useState("");
  const demo = new URLSearchParams(window.location.search).get("demo") === "1";
  const navigate = (hash: string) => { window.location.hash = hash; setView(currentView()); localStorage.setItem("logistria.view", hash); };
  const refresh = async () => {
    setRefreshError("");
    try {
      await load();
      if (activeRun) await selectRun(activeRun.run_id);
    } catch (failure) { setRefreshError(failure instanceof Error ? failure.message : "Unable to load console data"); }
  };
  useEffect(() => { const onHash = () => setView(currentView()); window.addEventListener("hashchange", onHash); if (!window.location.hash) navigate(localStorage.getItem("logistria.view") || "#/runs"); return () => window.removeEventListener("hashchange", onHash); }, []);
  useEffect(() => {
    if (demo) {
      const timers = demoEvents.map((event, index) => window.setTimeout(() => { useStore.getState().ingest({ ...event, ts: new Date().toISOString() }); setDemoEvents((current) => [...current, event]); }, index * 900));
      return () => timers.forEach(window.clearTimeout);
    }
    refresh(); return connect();
  }, [connect, demo]);
  useEffect(() => { if (!activeRun && runs[0]) selectRun(runs[0].run_id); }, [activeRun, runs, selectRun]);
  const selectedRunEvents = activeRun ? events.filter((event) => event.run_id === activeRun.run_id || event.payload_json.run_id === activeRun.run_id) : [];
  const displayedEvents = demo ? demoEventsState : selectedRunEvents;
  const label = demo ? runLabel(displayedEvents) : undefined;
  const exportCsv = () => { const rows = [["id", "run_id", "sender", "receiver", "type", "severity", "human_text", "ts"], ...events.map((event) => [event.id, event.run_id || "", event.sender, event.receiver, event.type, event.severity, event.human_text || "", event.ts])]; const csv = rows.map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(",")).join("\n"); const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); link.download = "logistria-audit.csv"; link.click(); };
  return <div className="app-shell"><Header connection={demo ? "connected" : connection} onSettings={() => setSettingsOpen(true)} /><div className="shell-body"><Sidebar view={view} onNavigate={navigate} expanded={expanded} onToggle={() => setExpanded(!expanded)} /><main className="war-room">{view === "runs" && <><div className="war-toolbar"><button className="button" onClick={() => setNewRunOpen(true)}>New run</button>{activeRun?.status === "completed" && <button className="button reject" onClick={() => replay(events.filter((event) => event.run_id === activeRun.run_id))}>Replay</button>}<RunSelector runs={runs} active={activeRun?.run_id} onSelect={selectRun} />{pendingEvents > 3 && <button className="skip-link" onClick={skipToLatest}>Skip to latest ({pendingEvents})</button>}</div><NewRun products={products} open={newRunOpen} onClose={() => setNewRunOpen(false)} onStarted={refresh} />{(error || refreshError) && <div className="error-banner" role="alert">{error || refreshError}</div>}<div className="run-header"><h1 className="run-title"><span className="product-dot" />{demo ? `${label?.product} x ${label?.quantity}` : activeRun ? `${activeRun.product_name} x ${activeRun.quantity}` : loading ? "Loading operations" : "No active run"}<span className="run-id mono">{demo ? "demo-run" : activeRun?.run_id || "Awaiting a run"}</span></h1><span className="status-word">{demo ? label?.status : activeRun?.status || "Ready"}</span></div><div className="console-grid"><div className="main-column">{loading && !demo ? <SkeletonRows count={3} /> : <Pipeline run={demo ? undefined : activeRun} events={displayedEvents} />}<EventFeed events={displayedEvents} loading={loading && !demo} demo={demo} /></div><aside className="side-column"><Suppliers run={activeRun} events={displayedEvents} /><DecisionPanel approvals={approvals} run={activeRun} events={displayedEvents} onRefresh={refresh} /><RoutePreview route={demo ? routeFromEvents(displayedEvents) : activeRun?.route || undefined} /></aside></div></>}{view === "inventory" && <InventoryView items={inventory} products={products} />}{view === "suppliers" && <SuppliersView suppliers={suppliers} />}{view === "audit" && <AuditView events={events} onExport={exportCsv} />}</main></div><SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} /></div>;
}
