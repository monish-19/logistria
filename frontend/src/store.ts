import { create } from "zustand";
import type { EventItem, RunDetail, RunSummary } from "./types";
import { api } from "./api";
import { eventFeedReducer, type FeedMessage } from "./eventFeed";

type Connection = "connecting" | "connected" | "offline";
interface State {
  events: EventItem[]; runs: RunSummary[]; activeRun?: RunDetail; connection: Connection; error?: string;
  adminKey: string; setAdminKey: (key: string) => void; ingest: (message: FeedMessage) => void;
  load: () => Promise<void>; selectRun: (id: string) => Promise<void>; connect: () => () => void;
}
const storedKey = typeof sessionStorage === "undefined" ? "" : sessionStorage.getItem("logistria.adminKey") || "";
export const useStore = create<State>((set, get) => ({
  events: [], runs: [], connection: "offline", adminKey: storedKey,
  setAdminKey: (adminKey) => { if (typeof sessionStorage !== "undefined") sessionStorage.setItem("logistria.adminKey", adminKey); set({ adminKey }); },
  ingest: (message) => set((state) => ({ events: eventFeedReducer(state.events, message) })),
  load: async () => {
    try { const [runs, events] = await Promise.all([api.runs(), api.events("?limit=50")]); set({ runs, events, error: undefined }); }
    catch (error) { set({ error: error instanceof Error ? error.message : "Unable to load operations" }); }
  },
  selectRun: async (id) => { try { set({ activeRun: await api.run(id) }); } catch (error) { set({ error: error instanceof Error ? error.message : "Unable to load run" }); } },
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
