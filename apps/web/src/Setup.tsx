import { useEffect, useRef, useState } from "react";
import { api, Camera, Floor, Member, Table, Zone } from "./api";
import type { Toast } from "./App";

type Props = { floor: Floor; refresh: () => void; toast: (t: string, k?: Toast["kind"]) => void };
type Tab = "tables" | "plan" | "zones" | "staff" | "camera" | "settings";

export function Setup(props: Props) {
  const [tab, setTab] = useState<Tab>("tables");
  const tabs: [Tab, string][] = [["tables", "Tables"], ["plan", "Floor plan"], ["zones", "Camera zones"], ["staff", "Staff"], ["camera", "Camera"], ["settings", "Settings"]];
  return (
    <main className="page" data-testid="setup">
      <h1>Setup</h1>
      <div className="seg tabs">{tabs.map(([k, label]) => (
        <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)} data-testid={`tab-${k}`}>{label}</button>))}</div>
      {tab === "tables" && <Tables {...props} />}
      {tab === "plan" && <Plan {...props} />}
      {tab === "zones" && <Zones {...props} />}
      {tab === "staff" && <Staff {...props} />}
      {tab === "camera" && <Cameras {...props} />}
      {tab === "settings" && <Settings {...props} />}
    </main>
  );
}

function useAct({ refresh, toast }: Props) {
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try { await fn(); if (ok) toast(ok); } catch (e) { toast((e as Error).message, "warn"); }
    refresh();
  };
}

function Tables(props: Props) {
  const { floor } = props;
  const rid = floor.restaurant.id;
  const act = useAct(props);
  const [label, setLabel] = useState("");
  const [capacity, setCapacity] = useState(4);
  return (
    <section className="card">
      <h2>Tables</h2>
      <table className="data">
        <thead><tr><th>Table ID</th><th>Seats</th><th>Smallest party</th><th /></tr></thead>
        <tbody>{floor.tables.map((t) => (
          <tr key={t.id}>
            <td><input defaultValue={t.label} aria-label="Table ID" onBlur={(e) => e.target.value !== t.label && act(() => api("PATCH", `/v1/restaurants/${rid}/tables/${t.id}`, { label: e.target.value }))} /></td>
            <td><input type="number" min={1} defaultValue={t.capacity} aria-label="Seats" onBlur={(e) => Number(e.target.value) !== t.capacity && act(() => api("PATCH", `/v1/restaurants/${rid}/tables/${t.id}`, { capacity: Number(e.target.value) }))} /></td>
            <td><input type="number" min={1} defaultValue={t.min_party} aria-label="Smallest party" onBlur={(e) => Number(e.target.value) !== t.min_party && act(() => api("PATCH", `/v1/restaurants/${rid}/tables/${t.id}`, { min_party: Number(e.target.value) }))} /></td>
            <td><button className="link" onClick={() => window.confirm(`Delete ${t.label} and its history?`) && act(() => api("DELETE", `/v1/restaurants/${rid}/tables/${t.id}`))}>Delete</button></td>
          </tr>))}
        </tbody>
      </table>
      <form className="row" onSubmit={(e) => { e.preventDefault(); act(() => api("POST", `/v1/restaurants/${rid}/tables`, { label, capacity }), `Added ${label}`); setLabel(""); }}>
        <input placeholder="New table ID, e.g. T13" value={label} onChange={(e) => setLabel(e.target.value)} required data-testid="new-table-label" />
        <input type="number" min={1} value={capacity} onChange={(e) => setCapacity(Number(e.target.value))} aria-label="Seats" />
        <button className="primary" data-testid="new-table-add">Add table</button>
      </form>
    </section>
  );
}

/** Convert a pointer event to 0..1 coordinates inside an element. */
function norm(e: { clientX: number; clientY: number }, el: Element): [number, number] {
  const r = el.getBoundingClientRect();
  const c = (v: number) => Math.round(Math.min(1, Math.max(0, v)) * 1000) / 1000;
  return [c((e.clientX - r.left) / r.width), c((e.clientY - r.top) / r.height)];
}

function Plan(props: Props) {
  const { floor } = props;
  const rid = floor.restaurant.id;
  const act = useAct(props);
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ id: string; x: number; y: number } | null>(null);
  return (
    <section className="card">
      <h2>Floor plan</h2>
      <p className="muted">Drag each table to where it stands in the room. Staff see this layout in the "Floor plan" view.</p>
      <div className="plan edit" ref={ref}
           onPointerMove={(e) => drag && ref.current && setDrag({ id: drag.id, x: norm(e, ref.current)[0], y: norm(e, ref.current)[1] })}
           onPointerUp={() => { if (drag) { act(() => api("PATCH", `/v1/restaurants/${rid}/tables/${drag.id}`, { x: drag.x, y: drag.y })); setDrag(null); } }}>
        {floor.tables.map((t) => {
          const p = drag?.id === t.id ? drag : t;
          return (
            <div key={t.id} className="spot chip" style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%` }}
                 onPointerDown={(e) => { e.preventDefault(); setDrag({ id: t.id, x: t.x, y: t.y }); }}>
              {t.label}<small>{t.capacity}</small>
            </div>);
        })}
      </div>
    </section>
  );
}

function Zones(props: Props) {
  const { floor, toast } = props;
  const rid = floor.restaurant.id;
  const [zones, setZones] = useState<Zone[]>([]);
  const [cams, setCams] = useState<Camera[]>([]);
  const [tableId, setTableId] = useState(floor.tables[0]?.id ?? "");
  const [draft, setDraft] = useState<[number, number][]>([]);
  const svg = useRef<SVGSVGElement>(null);
  const load = () => {
    api<Zone[]>("GET", `/v1/restaurants/${rid}/zones`).then(setZones);
    api<Camera[]>("GET", `/v1/restaurants/${rid}/cameras`).then(setCams);
  };
  useEffect(load, [rid]);
  const cam = cams[0];
  const current = zones.find((z) => z.table_id === tableId && z.camera_id === cam?.id);
  const label = (id: string) => floor.tables.find((t: Table) => t.id === id)?.label ?? "";
  const pts = (poly: [number, number][]) => poly.map(([x, y]) => `${x * 100},${y * 100}`).join(" ");
  const save = async (polygons: [number, number][][]) => {
    try {
      await api("PUT", `/v1/restaurants/${rid}/tables/${tableId}/zone`, { camera_id: cam.id, polygons });
      toast(`Zone saved for ${label(tableId)}. The camera picks it up within a minute.`);
      setDraft([]); load();
    } catch (e) { toast((e as Error).message, "warn"); }
  };
  if (!cam) return <section className="card"><h2>Camera zones</h2><p>Add a camera first (Camera tab).</p></section>;
  return (
    <section className="card">
      <h2>Camera zones</h2>
      <p className="muted">A zone is the area of the camera image where this table's guests sit. Pick a table, click to place
        at least three corners around its seats, then save. The frame below stands for the camera image
        (a still from the live camera appears here once the edge box supports snapshots).</p>
      <div className="row">
        <label className="inline">Table
          <select value={tableId} onChange={(e) => { setTableId(e.target.value); setDraft([]); }} data-testid="zone-table">
            {floor.tables.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </label>
        <button onClick={() => setDraft([])} disabled={!draft.length}>Clear drawing</button>
        <button className="primary" disabled={draft.length < 3} onClick={() => save([...(current?.polygons ?? []), draft])} data-testid="zone-add">Add seat zone</button>
        <button disabled={draft.length < 3} onClick={() => save([draft])}>Replace zones</button>
      </div>
      <svg ref={svg} className="zones" viewBox="0 0 100 100" preserveAspectRatio="none" data-testid="zone-canvas"
           onClick={(e) => svg.current && setDraft((d) => [...d, norm(e, svg.current!)])}>
        {zones.filter((z) => z.camera_id === cam.id).map((z) => z.polygons.map((poly, i) => (
          <g key={z.id + i}>
            <polygon points={pts(poly)} className={z.table_id === tableId ? "zone sel" : "zone"} />
            <text x={poly[0][0] * 100 + 1} y={poly[0][1] * 100 + 4}>{label(z.table_id)}</text>
          </g>)))}
        {draft.length > 0 && <polyline points={pts(draft)} className="draft" />}
        {draft.map(([x, y], i) => <circle key={i} cx={x * 100} cy={y * 100} r={0.9} className="pt" />)}
      </svg>
    </section>
  );
}

function Staff(props: Props) {
  const rid = props.floor.restaurant.id;
  const [members, setMembers] = useState<Member[]>([]);
  const [form, setForm] = useState({ name: "", email: "", role: "staff", password: "" });
  const load = () => { api<Member[]>("GET", `/v1/restaurants/${rid}/members`).then(setMembers); };
  useEffect(load, [rid]);
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    try { await fn(); if (ok) props.toast(ok); } catch (e) { props.toast((e as Error).message, "warn"); }
    load();
  };
  return (
    <section className="card">
      <h2>Staff</h2>
      <table className="data">
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th></tr></thead>
        <tbody>{members.map((m) => (
          <tr key={m.id} className={m.active ? "" : "muted"}>
            <td>{m.name}</td><td>{m.email}</td>
            <td><select value={m.role} onChange={(e) => run(() => api("PATCH", `/v1/restaurants/${rid}/members/${m.id}`, { role: e.target.value }))}>
              <option value="staff">Floor staff</option><option value="host">Host</option><option value="admin">Admin</option></select></td>
            <td><button className="link" onClick={() => run(() => api("PATCH", `/v1/restaurants/${rid}/members/${m.id}`, { active: !m.active }))}>
              {m.active ? "Deactivate" : "Reactivate"}</button></td>
          </tr>))}
        </tbody>
      </table>
      <h3>Add a staff member</h3>
      <form className="row wrap" onSubmit={(e) => { e.preventDefault(); run(() => api("POST", `/v1/restaurants/${rid}/members`, form), `Added ${form.name}`); setForm({ name: "", email: "", role: "staff", password: "" }); }}>
        <input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <input placeholder="Email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
          <option value="staff">Floor staff</option><option value="host">Host</option><option value="admin">Admin</option></select>
        <input placeholder="Temporary password (8+ characters)" type="text" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
        <button className="primary">Add</button>
      </form>
      <p className="muted">Give the temporary password to the staff member in person. Floor staff update tables and alerts;
        hosts also run the waitlist; admins also change setup and see analytics.</p>
    </section>
  );
}

function Cameras(props: Props) {
  const rid = props.floor.restaurant.id;
  const [cams, setCams] = useState<Camera[]>([]);
  const [token, setToken] = useState("");
  const [name, setName] = useState("");
  const load = () => { api<Camera[]>("GET", `/v1/restaurants/${rid}/cameras`).then(setCams); };
  useEffect(load, [rid, props.floor.cameras.map((c) => c.status).join()]);
  const show = async (p: Promise<{ device_token: string }>) => { setToken((await p).device_token); load(); };
  return (
    <section className="card">
      <h2>Camera</h2>
      <table className="data">
        <thead><tr><th>Name</th><th>Status</th><th>Last heartbeat</th><th /></tr></thead>
        <tbody>{cams.map((c) => (
          <tr key={c.id}>
            <td>{c.name}</td>
            <td><span className={"badge " + (c.status === "online" ? "ok" : "warn")}>{c.status}</span>{c.health === "degraded" && <span className="badge warn">{c.health_reason}</span>}</td>
            <td>{c.last_heartbeat_at ? new Date(c.last_heartbeat_at).toLocaleString() : "never"}</td>
            <td><button className="link" onClick={() => window.confirm("The current token stops working at once. Continue?") && show(api("POST", `/v1/restaurants/${rid}/cameras/${c.id}/rotate-token`))}>New device token</button></td>
          </tr>))}
        </tbody>
      </table>
      <form className="row" onSubmit={(e) => { e.preventDefault(); show(api("POST", `/v1/restaurants/${rid}/cameras`, { name })); setName(""); }}>
        <input placeholder="Camera name, e.g. Main room" value={name} onChange={(e) => setName(e.target.value)} required />
        <button>Add camera</button>
      </form>
      {token && <p className="banner warn">Device token (shown once; put it in the edge box's token file): <code>{token}</code></p>}
    </section>
  );
}

function Settings(props: Props) {
  const { floor } = props;
  const rid = floor.restaurant.id;
  const act = useAct(props);
  const patch = (body: object, ok: string) => act(() => api("PATCH", `/v1/restaurants/${rid}/settings`, body), ok);
  return (
    <section className="card">
      <h2>Settings</h2>
      <label className="check"><input type="checkbox" checked={floor.restaurant.automation_enabled} data-testid="automation"
        onChange={(e) => patch({ automation_enabled: e.target.checked }, e.target.checked ? "Camera automation on" : "Camera automation off: tables are manual")} />
        Camera updates tables automatically <span className="muted">(switch off to run the floor by hand)</span></label>
      <label className="check"><input type="checkbox" checked={!!floor.restaurant.settings.greet_reminders}
        onChange={(e) => patch({ greet_reminders: e.target.checked }, "Saved")} />
        Remind staff when newly seated guests have not been marked Greeted</label>
      <label>Time zone (used for reports)
        <input defaultValue={floor.restaurant.timezone} onBlur={(e) => e.target.value !== floor.restaurant.timezone && patch({ timezone: e.target.value }, "Time zone saved")} />
      </label>
    </section>
  );
}
