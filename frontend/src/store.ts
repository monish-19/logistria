import { create } from "zustand";
import type { Approval, EventItem, InventoryItem, Product, RunDetail, RunSummary, SupplierItem } from "./types";
import { api } from "./api";
import { eventFeedReducer, type FeedMessage } from "./eventFeed";

type Connection = "connecting" | "connected" | "offline";
interface State {
  events: EventItem[]; runs: RunSummary[]; products: Product[]; approvals: Approval[]; inventory: InventoryItem[]; suppliers: SupplierItem[]; activeRun?: RunDetail; connection: Connection; error?: string; loading: boolean;
  pendingEvents: number; adminKey: string; setAdminKey: (key: string) => void; ingest: (message: FeedMessage) => void; skipToLatest: () => void; replay: (items: EventItem[]) => void;
  applyEvent: (event: EventItem) => void; load: () => Promise<void>; selectRun: (id: string) => Promise<void>; approveRun: (id: string, approved: boolean) => Promise<Record<string, unknown>>; connect: () => () => void;
}
const storedKey = typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem("logistria.adminKey") || "";
let playbackQueue: FeedMessage[] = [];
let playbackTimer: number | undefined;
const messageEvent = (message: FeedMessage): EventItem => {
  const raw = "event" in message ? message.event : message;
  const candidate = raw as EventItem & { payload?: Record<string, unknown>; original_type?: string };
  return {
    ...candidate,
    type: candidate.original_type || candidate.type,
    payload_json: candidate.payload_json || candidate.payload || {},
  };
};
const eventRunId = (event: EventItem) => event.run_id || String(event.payload_json.run_id || "");
let eventSequence = -1;
export const useStore = create<State>((set, get) => ({
  events: [], runs: [], products: [], approvals: [], inventory: [], suppliers: [], pendingEvents: 0, connection: "offline", loading: false, adminKey: storedKey,
  setAdminKey: (adminKey) => { if (typeof sessionStorage !== "undefined") sessionStorage.setItem("logistria.adminKey", adminKey); set({ adminKey }); },
  applyEvent: (event) => {
    const normalized = { ...event, id: event.id ?? eventSequence--, run_id: eventRunId(event) || null };
    set((state) => {
      const sameAction = normalized.type === "human_action" && state.events.some((existing) =>
        existing.type === "human_action" &&
        existing.run_id === normalized.run_id &&
        Boolean(existing.payload_json.approved) === Boolean(normalized.payload_json.approved) &&
        String(existing.payload_json.supplier_name || "") === String(normalized.payload_json.supplier_name || ""));
      if (sameAction) return state;
      const events = eventFeedReducer(state.events, normalized);
      const runId = normalized.run_id;
      const status = String(normalized.payload_json.status || (normalized.payload_json.approved === false ? "rejected" : normalized.payload_json.approved === true ? "manufacturing" : ""));
      const runs = status && runId ? state.runs.map((run) => run.run_id === runId ? { ...run, status } : run) : state.runs;
      const activeRun = state.activeRun && runId === state.activeRun.run_id && status ? { ...state.activeRun, status } : state.activeRun;
      return { events, runs, activeRun };
    });
  },
  ingest: (message) => {
    const item = messageEvent(message);
    if (typeof window === "undefined") {
      get().applyEvent(item);
      return;
    }
    playbackQueue.push(message);
    set((state) => ({ pendingEvents: state.pendingEvents + 1 }));
    const consume = () => {
      const next = playbackQueue.shift();
      if (!next) { playbackTimer = undefined; return; }
      get().applyEvent(messageEvent(next));
      set((state) => ({ pendingEvents: Math.max(0, state.pendingEvents - 1) }));
      const nextEvent = messageEvent(next);
      playbackTimer = window.setTimeout(consume, nextEvent.sender === "ManufacturingStep" && nextEvent.payload_json.progress_pct !== undefined ? 450 : 700);
    };
    if (!playbackTimer) { playbackTimer = window.setTimeout(consume, item.sender === "ManufacturingStep" && item.payload_json.progress_pct !== undefined ? 450 : 700); }
  },
  skipToLatest: () => {
    if (playbackTimer) window.clearTimeout(playbackTimer);
    playbackTimer = undefined;
    const queued = playbackQueue.splice(0);
    queued.forEach((message) => get().applyEvent(messageEvent(message)));
    set({ pendingEvents: 0 });
  },
  replay: (items) => { if (playbackTimer) window.clearTimeout(playbackTimer); playbackTimer = undefined; playbackQueue = []; set({ events: [], pendingEvents: 0 }); items.forEach((item) => get().ingest(item)); },
  load: async () => {
    set({ loading: true });
    try {
      const [runs, events, products, approvals, inventory, suppliers] = await Promise.all([
        api.runs(),
        api.events("?limit=500"),
        typeof api.products === "function" ? api.products() : Promise.resolve([]),
        typeof api.approvals === "function" ? api.approvals() : Promise.resolve([]),
        typeof api.inventory === "function" ? api.inventory() : Promise.resolve([]),
        typeof api.suppliers === "function" ? api.suppliers() : Promise.resolve([]),
      ]);
      set({ runs, products, approvals, inventory, suppliers, events: [], pendingEvents: 0, error: undefined });
      events.forEach((event) => get().applyEvent(event));
    }
    catch (error) { set({ error: error instanceof Error ? error.message : "Unable to load operations" }); }
    finally { set({ loading: false }); }
  },
  selectRun: async (id) => { try { set({ activeRun: await api.run(id) }); } catch (error) { set({ error: error instanceof Error ? error.message : "Unable to load run" }); } },
  approveRun: async (id, approved) => {
    const current = get().activeRun;
    const result = await api.approve(id, get().adminKey, approved);
    get().applyEvent({
      id: eventSequence--,
      run_id: id,
      sender: "Admin",
      receiver: "ProcurementAgent",
      type: "human_action",
      payload_json: { approved, product_name: current?.product_name, supplier_name: current?.selected_supplier?.name },
      human_text: `You ${approved ? "approved" : "rejected"} ${current?.selected_supplier?.name || "the supplier"} PO, $4,250`,
      severity: approved ? "success" : "warning",
      ts: new Date().toISOString(),
    });
    const status = String(result.status || (approved ? "manufacturing" : "rejected"));
    set((state) => ({ activeRun: state.activeRun?.run_id === id ? { ...state.activeRun, status } : state.activeRun, runs: state.runs.map((run) => run.run_id === id ? { ...run, status } : run) }));
    const detail = await api.run(id);
    set((state) => ({ activeRun: state.activeRun?.run_id === id ? detail : state.activeRun }));
    const refreshed = await api.events(`?run_id=${encodeURIComponent(id)}&limit=500`);
    refreshed.forEach((event) => get().applyEvent(event));
    if (status === "pending_human_review") {
      const started = Date.now();
      while (Date.now() - started < 20000) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const polled = await api.run(id);
        set((state) => ({ activeRun: state.activeRun?.run_id === id ? polled : state.activeRun, runs: state.runs.map((run) => run.run_id === id ? { ...run, status: polled.status } : run) }));
        if (polled.status !== "pending_human_review") break;
      }
    }
    return result;
  },
  connect: () => {
    let socket: WebSocket; let stopped = false; let timer: number | undefined;
    const open = () => {
      if (stopped) return; set({ connection: "connecting" });
      const token = get().adminKey ? `?token=${encodeURIComponent(get().adminKey)}` : "";
      socket = new WebSocket(`${import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws/events"}${token}`);
      socket.onopen = () => set({ connection: "connected" });
      socket.onmessage = (event) => { try { get().ingest(JSON.parse(event.data) as FeedMessage); } catch { /* malformed server frame */ } };
      socket.onclose = () => { set({ connection: "offline" }); if (!stopped) timer = window.setTimeout(open, 2500); };
      socket.onerror = () => set({ connection: "offline" });
    };
    open(); return () => { stopped = true; if (timer) window.clearTimeout(timer); socket?.close(); };
  },
}));
