import { useEffect, useRef, useState } from "react";
import { Activity, Box, Check, FileText, RefreshCw, Settings2, Users, X } from "lucide-react";
import { CircleMarker, MapContainer, Polyline, TileLayer, useMap } from "react-leaflet";
import { LatLngBounds } from "leaflet";
import { api } from "./api";
import { useStore } from "./store";
import type { Approval, EventItem, InventoryItem, Product, RouteOutput, RunDetail, RunSummary, SupplierItem } from "./types";
import { deriveNodes, PIPELINE_NODES } from "./pipeline";

export function Button({ children, reject = false, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { reject?: boolean }) {
  return <button className={`button${reject ? " reject" : ""}`} {...props}>{children}</button>;
}

export function SkeletonRows({ count = 4 }: { count?: number }) {
  return <div className="skeleton-list" aria-label="Loading"><span className="sr-only">Loading</span>{Array.from({ length: count }, (_, index) => <div className="skeleton-row" key={index}><span /><span /><span /></div>)}</div>;
}

export function Marker({ status }: { status: string }) {
  return <span className={`marker ${status === "done" ? "done" : status === "active" ? "active" : status === "paused" ? "review" : ""}`}>{status === "done" && <Check size={10} />}</span>;
}

export function FeedRow({ event, isNew = false }: { event: EventItem; isNew?: boolean }) {
  const sentence = (event.human_text || "Agent message received.").split(/[.!?]/)[0].split(" ").slice(0, 8).join(" ");
  const product = String(event.payload_json.product_name || "Operations");
  return <article className={`feed-row${isNew ? " new" : ""}`} style={{ "--product-color": productColor(product) } as React.CSSProperties}><time>{new Date(event.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}</time><span className="feed-product"><i style={{ background: productColor(product) }} />{product}</span><span className="feed-agent">{event.sender}</span><span className="feed-message">{sentence}</span></article>;
}

const productColors = ["var(--product-1)", "var(--product-2)", "var(--product-3)", "var(--product-4)", "var(--product-5)", "var(--product-6)", "var(--product-7)", "var(--product-8)"];
function productColor(name: string) { if (name === "System") return "var(--system)"; return productColors[[...name].reduce((hash, char) => ((hash * 31) + char.charCodeAt(0)) >>> 0, 7) % productColors.length]; }

export function KeyValue({ label, value }: { label: string; value: React.ReactNode }) {
  return <dl className="key-value"><dt>{label}</dt><dd>{value}</dd></dl>;
}

export function SupplierRow({ name, match, price, selected = false }: { name: string; match: number; price: string; selected?: boolean }) {
  return <div className={`supplier-row${selected ? " selected" : ""}`}><span className="supplier-name">{name}</span><span className="supplier-price">{price}</span><span className="match-bar"><span style={{ width: `${match}%` }} /></span><span className="match-value">{match}% match</span></div>;
}

export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const key = useStore((state) => state.adminKey);
  const setKey = useStore((state) => state.setAdminKey);
  const [value, setValue] = useState(key);
  if (!open) return null;
  return <div className="modal-backdrop"><div className="modal"><div className="run-header"><h2>Operator settings</h2><button className="icon-button" onClick={onClose} aria-label="Close settings"><X size={16} /></button></div><p className="empty-state">The admin key is held in this browser session only.</p><label>Admin API key<input className="field" type="password" value={value} onChange={(event) => setValue(event.target.value)} /></label><Button onClick={() => { setKey(value); onClose(); }}>Save session key</Button></div></div>;
}

export function StartForm({ products, onStarted }: { products: Product[]; onStarted: () => void }) {
  const key = useStore((state) => state.adminKey);
  const [product, setProduct] = useState("");
  const [quantity, setQuantity] = useState("10");
  const [urgency, setUrgency] = useState("normal");
  const [error, setError] = useState("");
  useEffect(() => { if (!product && products[0]) setProduct(products[0].name); }, [products, product]);
  const submit = async () => { setError(""); try { await api.start({ product_name: product, quantity: Number(quantity), urgency }, key); onStarted(); } catch (err) { setError(err instanceof Error ? err.message : "Could not start"); } };
  return <div className="start-form" onKeyDown={(event) => { if (event.key === "Enter" && product) { event.preventDefault(); void submit(); } }}><select className="field compact" value={product} onChange={(event) => setProduct(event.target.value)}><option value="">Select product</option>{products.map((item) => <option key={item.id}>{item.name}</option>)}</select><input className="field compact" type="number" min="1" value={quantity} onChange={(event) => setQuantity(event.target.value)} aria-label="Quantity" /><select className="field compact" value={urgency} onChange={(event) => setUrgency(event.target.value)} aria-label="Urgency"><option>normal</option><option>high</option></select><Button disabled={!product} onClick={submit}>{error || "Start production"}</Button></div>;
}

export function EventFeed({ events, loading, demo = false }: { events?: EventItem[]; loading?: boolean; demo?: boolean }) {
  const storeEvents = useStore((state) => state.events);
  const visibleEvents = events ?? storeEvents;
  const seenIds = useRef(new Set<number>());
  useEffect(() => { visibleEvents.forEach((event) => seenIds.current.add(event.id)); }, [visibleEvents]);
  const hydrated = !demo && seenIds.current.size > 0;
  const [filter, setFilter] = useState(() => sessionStorage.getItem("logistria.feed-filter") || "all");
  const products = [...new Set(visibleEvents.map((event) => String(event.payload_json.product_name || "System")))];
  const filtered = visibleEvents.filter((event) => filter === "all" || (filter === "alerts" ? ["alert", "escalation", "warning"].includes(event.severity) : String(event.payload_json.product_name || "System") === filter));
  const groups = [...new Set(filtered.map((event) => event.run_id || "platform"))];
  const choose = (value: string) => { setFilter(value); sessionStorage.setItem("logistria.feed-filter", value); };
  return <section className="feed-section"><div className="feed-heading"><h2>Event feed</h2><span className="mono">{filtered.length} events</span></div><div className="feed-filters"><button className={`filter-chip${filter === "all" ? " selected" : ""}`} onClick={() => choose("all")}>All</button>{products.map((product) => <button className={`filter-chip${filter === product ? " selected" : ""}`} key={product} onClick={() => choose(product)}><i style={{ background: productColor(product) }} />{product}</button>)}<button className={`filter-chip${filter === "alerts" ? " selected" : ""}`} onClick={() => choose("alerts")}>Alerts</button></div><div className="feed-scroll">{loading ? <SkeletonRows count={6} /> : filtered.length ? groups.map((group) => <div className="feed-group" key={group}><div className="feed-group-header">{group}</div>{filtered.filter((event) => (event.run_id || "platform") === group).slice().reverse().map((event) => <FeedRow event={event} key={event.id} isNew={demo ? !seenIds.current.has(event.id) : hydrated && !seenIds.current.has(event.id)} />)}</div>) : <div className="empty-state">No events match this filter.</div>}</div></section>;
}

export function Pipeline({ run, events }: { run?: RunDetail; events: EventItem[] }) {
  const nodes = deriveNodes(run, events);
  const scopedEvents = events.filter((event) => event.run_id === run?.run_id || event.payload_json.run_id === run?.run_id);
  const progress = Math.max(0, ...scopedEvents.filter((event) => event.sender === "ManufacturingStep").map((event) => Number(event.payload_json.progress_pct || 0)));
  return <section className="pipeline-track"><h2>Pipeline</h2><div className="pipeline-list">{PIPELINE_NODES.map((node, index) => <div className="pipeline-step" key={node}><span className={`pipeline-segment ${index === 0 || nodes[PIPELINE_NODES[index - 1]] === "done" ? "filled" : ""}`} /><Marker status={nodes[node]} /><span className="pipeline-label">{node[0].toUpperCase() + node.slice(1)}</span><span className="pipeline-state">{node === "manufacturing" && progress > 0 ? `${progress}%` : nodes[node] === "active" ? "In progress" : nodes[node] === "paused" ? "Review" : nodes[node]}</span>{node === "manufacturing" && progress > 0 ? <span className="progress-bar"><i style={{ width: `${progress}%` }} /></span> : nodes[node] === "active" && <span className="indeterminate-bar" />}</div>)}</div></section>;
}

export function Suppliers({ run, events }: { run?: RunDetail; events: EventItem[] }) {
  const ranking = events.slice().reverse().find((event) => event.sender === "SupplierRankingAgent" && event.payload_json.top_pick);
  const selected = String(ranking?.payload_json.top_pick || run?.selected_supplier?.name || "Apex Industrial");
  return <section className="side-section"><h2>Suppliers</h2><SupplierRow name={selected} match={96} price="$4,250" selected /><SupplierRow name="Vanguard Logistics" match={82} price="$4,100" /><SupplierRow name="Global Components" match={64} price="$4,600" /></section>;
}

export function DecisionPanel({ approvals, run, events, onRefresh }: { approvals: Approval[]; run?: RunDetail; events: EventItem[]; onRefresh: () => void }) {
  const approveRun = useStore((state) => state.approveRun);
  const approval = approvals.find((item) => item.run_id === run?.run_id);
  const reviewRunId = run?.run_id;
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const decide = async (approved: boolean) => {
    if (!reviewRunId || submitting) return;
    setSubmitting(true); setError("");
    try { await approveRun(reviewRunId, approved); onRefresh(); }
    catch (failure) { const status = Number((failure as { status?: number }).status); setError(status === 401 || status === 403 ? "Admin key required" : "Try again"); }
    finally { setSubmitting(false); }
  };
  useEffect(() => {
    if (!approval || submitting) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName) || target.isContentEditable) return;
      if (event.key.toLowerCase() === "a") void decide(true);
      if (event.key.toLowerCase() === "r") void decide(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [approval, reviewRunId, submitting]);
  if (run?.status !== "pending_human_review") return null;
  if (approval) return <section className="decision-block"><h2>Decision required</h2><KeyValue label="Vendor" value={String(run?.selected_supplier?.name || "Apex Industrial")} /><KeyValue label="Total" value="$4,250" /><KeyValue label="Delivery" value="2 business days" />{error && <p className="error-text">{error}</p>}<div className="decision-actions"><Button disabled={!reviewRunId || submitting} onClick={() => void decide(true)}>{submitting ? "Submitting..." : "Approve"} <span className="shortcut">A</span></Button><Button reject disabled={!reviewRunId || submitting} onClick={() => void decide(false)}>Reject <span className="shortcut">R</span></Button></div></section>;
  return <section className="side-section"><h2>Route and production</h2><div className="summary-list"><KeyValue label="Production" value={run?.status || "Complete"} /><KeyValue label="Distance" value={`${run?.distance_km?.toFixed(1) || "—"} km`} /><KeyValue label="Delivery" value={`${run?.eta_minutes?.toFixed(0) || "—"} min`} /></div></section>;
}

export function RoutePreview({ route }: { route?: RouteOutput }) {
  const [mapFailed, setMapFailed] = useState(false);
  const coordinates = route?.geometry && !Array.isArray(route.geometry) ? route.geometry.coordinates : Array.isArray(route?.geometry) ? route.geometry : route?.stops?.map((stop) => [stop.lon, stop.lat] as [number, number]) || [];
  if (coordinates.length < 2) return null;
  const xs = coordinates.map(([x]) => x);
  const ys = coordinates.map(([, y]) => y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const points = coordinates.map(([x, y]) => `${10 + ((x - minX) / (maxX - minX || 1)) * 180},${70 - ((y - minY) / (maxY - minY || 1)) * 55}`).join(" ");
  const pointList = points.split(" ");
  const start = pointList[0].split(",");
  const end = pointList[pointList.length - 1].split(",");
  return <section className="route-preview side-section"><h2>Route</h2>{mapFailed ? <svg className="route-fallback" viewBox="0 0 200 80" aria-label="Delivery route"><polyline points={points} /><circle cx={start[0]} cy={start[1]} r="3" /><circle cx={end[0]} cy={end[1]} r="3" /></svg> : <RouteMap coordinates={coordinates} onTileError={() => setMapFailed(true)} />}<div className="summary-list"><KeyValue label="Distance" value={`${route?.distance_km?.toFixed(1) || "—"} km${route?.method === "haversine" ? " · Straight-line estimate" : ""}`} /><KeyValue label="ETA" value={`${route?.eta_minutes?.toFixed(0) || "—"} min`} /></div></section>;
}

function FitRoute({ coordinates }: { coordinates: [number, number][] }) {
  const map = useMap();
  useEffect(() => { map.fitBounds(new LatLngBounds(coordinates.map(([lng, lat]) => [lat, lng])), { padding: [24, 24] }); }, [coordinates, map]);
  return null;
}

function RouteMap({ coordinates, onTileError }: { coordinates: [number, number][]; onTileError: () => void }) {
  const positions = coordinates.map(([lng, lat]) => [lat, lng] as [number, number]);
  return <div className="route-map"><MapContainer center={positions[0]} zoom={10} scrollWheelZoom={false} attributionControl><TileLayer eventHandlers={{ tileerror: onTileError }} url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" attribution='&copy; OpenStreetMap &copy; CARTO' /><FitRoute coordinates={coordinates} /><Polyline positions={positions} pathOptions={{ color: "var(--accent)", weight: 3, className: "route-line" }} /><CircleMarker center={positions[0]} radius={6} pathOptions={{ color: "var(--ink)", fill: false, weight: 2 }} /><CircleMarker center={positions[positions.length - 1]} radius={6} pathOptions={{ color: "var(--ink)", fillColor: "var(--ink)", fillOpacity: 1 }} /></MapContainer></div>;
}

export function RunSelector({ runs, active, onSelect }: { runs: RunSummary[]; active?: string; onSelect: (id: string) => void }) {
  return <select className="field compact" value={active || ""} onChange={(event) => onSelect(event.target.value)} aria-label="Active run"><option value="">Active run</option>{runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.product_name} · {run.run_id.slice(0, 8)}</option>)}</select>;
}

export function Header({ connection, onSettings }: { connection: string; onSettings: () => void }) {
  return <header className="top-nav"><span className="brand">Logistria</span><div className="nav-actions"><span className="connection"><span className={`connection-dot ${connection}`} />{connection === "connected" ? "Live" : connection}</span><span>Mock ERP</span><button className="icon-button" onClick={onSettings} aria-label="Open settings"><Settings2 size={16} /></button><button className="icon-button" onClick={() => useStore.getState().load()} aria-label="Refresh"><RefreshCw size={15} /></button></div></header>;
}

const navItems = [
  { hash: "#/runs", label: "Runs", icon: Activity },
  { hash: "#/inventory", label: "Inventory", icon: Box },
  { hash: "#/suppliers", label: "Suppliers", icon: Users },
  { hash: "#/audit", label: "Audit log", icon: FileText },
];
export function Sidebar({ view, onNavigate, expanded, onToggle }: { view: string; onNavigate: (hash: string) => void; expanded: boolean; onToggle: () => void }) {
  return <aside className={`sidebar${expanded ? " expanded" : ""}`}><button className="sidebar-toggle icon-button" onClick={onToggle} aria-label="Toggle navigation">{expanded ? "‹" : "›"}</button>{navItems.map(({ hash, label, icon: Icon }) => <button key={hash} className={`sidebar-item${view === hash.slice(2) ? " active" : ""}`} title={label} onClick={() => onNavigate(hash)}><Icon size={17} /><span>{label}</span></button>)}</aside>;
}

export function NewRun({ products, open, onClose, onStarted }: { products: Product[]; open: boolean; onClose: () => void; onStarted: () => void }) {
  const key = useStore((state) => state.adminKey);
  const [product, setProduct] = useState("");
  const [quantity, setQuantity] = useState("10");
  const [urgency, setUrgency] = useState("normal");
  const [dueDate, setDueDate] = useState("");
  const [error, setError] = useState("");
  if (!open) return null;
  const submit = async () => { try { await api.start({ product_name: product, quantity: Number(quantity), urgency, due_date: dueDate || null }, key); onStarted(); onClose(); } catch (err) { setError(err instanceof Error ? err.message : "Could not start run"); } };
  return <div className="popover new-run"><h2>New run</h2><select className="field" value={product} onChange={(event) => setProduct(event.target.value)}><option value="">Select product</option>{products.map((item) => <option key={item.id}>{item.name}</option>)}</select><input className="field" type="number" min="1" value={quantity} onChange={(event) => setQuantity(event.target.value)} placeholder="Quantity" /><div className="segmented"><button className={urgency === "normal" ? "selected" : ""} onClick={() => setUrgency("normal")}>Normal</button><button className={urgency === "high" ? "selected" : ""} onClick={() => setUrgency("high")}>High</button></div><input className="field" type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} />{error && <p className="error-text">{error}</p>}<div className="decision-actions"><Button reject onClick={onClose}>Cancel</Button><Button disabled={!product} onClick={submit}>Start</Button></div></div>;
}

export function InventoryView({ items, products }: { items: InventoryItem[]; products: Product[] }) {
  return <ViewShell title="Inventory" intro={items.length ? "Current stock from the inventory endpoint." : "No inventory records are available."}><table className="data-table"><thead><tr><th>Material</th><th>SKU</th><th>Available</th><th>Reserved</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{item.material}</td><td className="mono">{item.sku || "—"}</td><td className="mono">{item.available_qty}</td><td className="mono">{item.reserved_qty}</td></tr>)}</tbody></table>{!items.length && <div className="empty-state">Inventory endpoint returned no records.</div>}</ViewShell>;
}

export function SuppliersView({ suppliers }: { suppliers: SupplierItem[] }) {
  return <ViewShell title="Suppliers" intro={suppliers.length ? "Supplier records from the existing adapter endpoint." : "No supplier records are available."}><table className="data-table"><thead><tr><th>Supplier</th><th>Type</th><th>Materials</th><th>Prices</th></tr></thead><tbody>{suppliers.map((supplier) => <tr key={supplier.id}><td>{supplier.name}</td><td>{supplier.is_cold_start ? "Cold start" : "Established"}</td><td>{supplier.materials.length}</td><td className="mono">{supplier.materials.map((item) => `$${item.unit_price.toFixed(2)}`).join(", ") || "—"}</td></tr>)}</tbody></table>{!suppliers.length && <div className="empty-state">Suppliers endpoint returned no records.</div>}</ViewShell>;
}

export function ViewShell({ title, intro, children }: { title: string; intro: string; children: React.ReactNode }) {
  return <section className="list-view"><h1>{title}</h1><p className="view-intro">{intro}</p>{children}</section>;
}

export function AuditView({ events, onExport }: { events: EventItem[]; onExport: () => void }) {
  const [query, setQuery] = useState("");
  const [agent, setAgent] = useState("");
  const [run, setRun] = useState("");
  const [alerts, setAlerts] = useState(false);
  const products = [...new Set(events.map((event) => String(event.payload_json.product_name || "" )).filter(Boolean))];
  const filtered = events.filter((event) => {
    const text = `${event.sender} ${event.human_text || ""} ${event.run_id || ""}`.toLowerCase();
    return (!query || text.includes(query.toLowerCase())) && (!agent || event.sender === agent) && (!run || event.run_id === run) && (!alerts || ["alert", "escalation"].includes(event.type));
  }).slice().reverse();
  return <ViewShell title="Audit log" intro="All events across runs, newest first."><div className="filter-row"><input className="field" placeholder="Filter product or text" value={query} onChange={(event) => setQuery(event.target.value)} /><select className="field" value={agent} onChange={(event) => setAgent(event.target.value)}><option value="">All agents</option>{[...new Set(events.map((event) => event.sender))].map((value) => <option key={value}>{value}</option>)}</select><select className="field" value={run} onChange={(event) => setRun(event.target.value)}><option value="">All runs</option>{[...new Set(events.map((event) => event.run_id).filter(Boolean))].map((value) => <option key={value}>{value}</option>)}</select><button className={`filter-chip${alerts ? " selected" : ""}`} onClick={() => setAlerts(!alerts)}>Alerts</button><Button onClick={onExport}>Export CSV</Button></div><table className="data-table"><thead><tr><th>Time</th><th>Product</th><th>Agent</th><th>Run</th><th>Message</th></tr></thead><tbody>{filtered.map((event) => <tr key={event.id}><td className="mono">{new Date(event.ts).toLocaleString()}</td><td>{String(event.payload_json.product_name || products.find((product) => event.human_text?.includes(product)) || "—")}</td><td>{event.sender}</td><td className="mono">{event.run_id || "platform"}</td><td>{event.human_text || "—"}</td></tr>)}</tbody></table>{!filtered.length && <div className="empty-state">No events match these filters.</div>}</ViewShell>;
}
