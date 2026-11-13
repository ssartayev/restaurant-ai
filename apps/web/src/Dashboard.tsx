import { useEffect, useState } from "react";
import { api, ApiError, atLeast, duration, Floor, Party, Role, STATE_ICON, STATE_LABEL, Table, TableEvent } from "./api";
import type { Toast } from "./App";

type Props = { floor: Floor; offset: number; refresh: () => void; toast: (t: string, k?: Toast["kind"]) => void; reloadMe: () => void };

function useNow(offset: number) {
  const [now, setNow] = useState(Date.now() + offset);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() + offset), 1000);
    return () => window.clearInterval(id);
  }, [offset]);
  return now;
}

export function Dashboard({ floor, offset, refresh, toast, reloadMe }: Props) {
  const now = useNow(offset);
  const [view, setView] = useState<"grid" | "plan">(() => (localStorage.getItem("view") as "grid" | "plan") || "grid");
  const [history, setHistory] = useState<Table | null>(null);
  const rid = floor.restaurant.id;
  const role = floor.role;
  const partyById = new Map(floor.waitlist.map((p) => [p.id, p]));
  const suggestion = new Map(floor.suggestions.map((s) => [s.table_id, partyById.get(s.party_id)]));
  const tableOfParty = new Map(floor.suggestions.map((s) => [s.party_id, floor.tables.find((t) => t.id === s.table_id)]));
  const offline = floor.cameras.filter((c) => c.status === "offline");
  const degraded = floor.cameras.filter((c) => c.status === "online" && c.health === "degraded");

  const command = async (t: Table, cmd: string) => {
    try {
      await api("POST", `/v1/restaurants/${rid}/tables/${t.id}/commands`, { command: cmd, expected_version: t.version });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const d = e.detail;
        toast(`${t.label} was already changed${d?.changed_by ? " by " + d.changed_by : ""}. Now: ${STATE_LABEL[d.table.state as Table["state"]]}.`, "warn");
      } else toast((e as Error).message, "warn");
    }
    refresh();
  };
  const seat = async (t: Table, p: Party) => {
    try {
      await api("POST", `/v1/restaurants/${rid}/tables/${t.id}/seat`, { party_id: p.id, expected_version: t.version });
      toast(`${p.name ?? "Party"} (${p.party_size}) seated at ${t.label}`);
    } catch (e) {
      toast(e instanceof ApiError && e.status === 409 ? `${t.label} is no longer ready` : (e as Error).message, "warn");
    }
    refresh();
  };
  const ack = async (alertId: string) => { await api("POST", `/v1/restaurants/${rid}/alerts/${alertId}/ack`); refresh(); };

  const counts = { ready: 0, occupied: 0, needs_clearing: 0 };
  floor.tables.forEach((t) => counts[t.state]++);

  const card = (t: Table) => (
    <TableCard key={t.id} t={t} now={now} role={role} floor={floor} suggested={suggestion.get(t.id)}
               onCommand={command} onSeat={seat} onAck={ack} onHistory={() => setHistory(t)} />
  );

  return (
    <main className="dash">
      {floor.restaurant.is_demo && <DemoBar floor={floor} refresh={refresh} toast={toast} reloadMe={reloadMe} />}
      {offline.length > 0 && (
        <div className="banner bad" role="alert" data-testid="offline-banner">
          Camera offline. Tables do not update by themselves: use the buttons on each table.
        </div>
      )}
      {!floor.restaurant.automation_enabled && (
        <div className="banner bad" role="alert">Camera automation is switched off. All tables are manual.</div>
      )}
      {degraded.length > 0 && (
        <div className="banner warn">Camera image is poor ({degraded[0].health_reason ?? "unknown reason"}). Check tables by eye.</div>
      )}
      <div className="cols">
        <section className="floor">
          <div className="bar">
            <span className="pill ready" data-testid="count-ready">{STATE_ICON.ready} {counts.ready} ready</span>
            <span className="pill occupied">{STATE_ICON.occupied} {counts.occupied} occupied</span>
            <span className="pill needs_clearing" data-testid="count-clearing">{STATE_ICON.needs_clearing} {counts.needs_clearing} to clear</span>
            <span className="spacer" />
            <div className="seg" role="group" aria-label="View">
              <button className={view === "grid" ? "on" : ""} onClick={() => { setView("grid"); localStorage.setItem("view", "grid"); }}>Grid</button>
              <button className={view === "plan" ? "on" : ""} onClick={() => { setView("plan"); localStorage.setItem("view", "plan"); }}>Floor plan</button>
            </div>
          </div>
          {view === "grid"
            ? <div className="grid">{floor.tables.map(card)}</div>
            : <div className="plan">{floor.tables.map((t) => (
                <div key={t.id} className="spot" style={{ left: `${t.x * 100}%`, top: `${t.y * 100}%` }}>{card(t)}</div>))}
              </div>}
        </section>
        <aside className="side">
          <Alerts floor={floor} now={now} onAck={ack} />
          <Waitlist floor={floor} now={now} role={role} tableOfParty={tableOfParty} refresh={refresh} onSeat={seat} toast={toast} />
        </aside>
      </div>
      {history && <History rid={rid} table={history} onClose={() => setHistory(null)} />}
    </main>
  );
}

function TableCard({ t, now, role, floor, suggested, onCommand, onSeat, onAck, onHistory }: {
  t: Table; now: number; role: Role; floor: Floor; suggested: Party | undefined;
  onCommand: (t: Table, c: string) => void; onSeat: (t: Table, p: Party) => void;
  onAck: (id: string) => void; onHistory: () => void;
}) {
  const alerts = floor.alerts.filter((a) => a.table_id === t.id);
  const clearing = alerts.find((a) => a.type === "needs_clearing");
  const greet = alerts.find((a) => a.type === "greet_reminder");
  const greetOn = !!floor.restaurant.settings.greet_reminders;
  return (
    <article className={`table ${t.state}`} data-testid={`table-${t.label}`} data-state={t.state}>
      <header>
        <h3>{t.label}</h3>
        <span className="cap" title="Seats">{t.capacity} seats</span>
      </header>
      <div className="state"><span className="icon" aria-hidden>{STATE_ICON[t.state]}</span> {STATE_LABEL[t.state]}</div>
      <div className="timer" title="Time in this state">{duration(now - new Date(t.state_since).getTime())}</div>
      <div className="badges">
        {t.manual_hold && <span className="badge" title="Set by staff. The camera resumes once it agrees with this state." data-testid={`manual-${t.label}`}>Manual</span>}
        {clearing && <span className="badge warn">{clearing.status === "open" ? "Not acknowledged" : `Ack: ${clearing.acknowledged_by}`}</span>}
        {greet && <span className="badge warn">Greet guests</span>}
        {t.state === "occupied" && t.greeted_at && <span className="badge ok">Greeted</span>}
      </div>
      {t.guests_seated_hint && <p className="hint">Guests seated here? <button className="link" onClick={() => onCommand(t, "mark_occupied")}>Yes, occupied</button></p>}
      <div className="actions">
        {t.state === "ready" && suggested && atLeast(role, "host") && (
          <button className="primary" data-testid={`seat-${t.label}`} onClick={() => onSeat(t, suggested)}>
            Seat {suggested.name} ({suggested.party_size})
          </button>)}
        {t.state === "ready" && <button onClick={() => onCommand(t, "mark_occupied")}>Mark occupied</button>}
        {t.state === "occupied" && <button onClick={() => onCommand(t, "mark_needs_clearing")}>Party left</button>}
        {t.state === "occupied" && greetOn && !t.greeted_at && <button onClick={() => onCommand(t, "mark_greeted")}>Greeted</button>}
        {t.state === "needs_clearing" && clearing?.status === "open" && (
          <button data-testid={`ack-${t.label}`} onClick={() => onAck(clearing.id)}>Acknowledge</button>)}
        {t.state === "needs_clearing" && (
          <button className="primary" data-testid={`ready-${t.label}`} onClick={() => onCommand(t, "mark_ready")}>Mark ready</button>)}
        {t.state === "needs_clearing" && <button onClick={() => onCommand(t, "mark_occupied")}>Still occupied</button>}
      </div>
      <div className="more">
        {t.manual_hold && <button className="link" onClick={() => onCommand(t, "resume_camera")}>Resume camera</button>}
        <button className="link" data-testid={`history-${t.label}`} onClick={onHistory}>History</button>
      </div>
    </article>
  );
}

function Alerts({ floor, now, onAck }: { floor: Floor; now: number; onAck: (id: string) => void }) {
  const label = (id: string) => floor.tables.find((t) => t.id === id)?.label ?? "?";
  return (
    <section className="card" data-testid="alerts">
      <h2>Alerts <span className="count">{floor.alerts.filter((a) => a.status === "open").length}</span></h2>
      {floor.alerts.length === 0 && <p className="muted">Nothing needs attention.</p>}
      <ul className="list">
        {floor.alerts.map((a) => (
          <li key={a.id} className={a.status}>
            <div>
              <strong>{label(a.table_id)}</strong> {a.type === "needs_clearing" ? "needs clearing" : "guests not greeted"}
              <div className="muted">{duration(now - new Date(a.created_at).getTime())} ago
                {a.acknowledged_by ? ` · ${a.acknowledged_by} is on it` : ""}</div>
            </div>
            {a.status === "open" && <button onClick={() => onAck(a.id)}>Acknowledge</button>}
          </li>))}
      </ul>
    </section>
  );
}

function Waitlist({ floor, now, role, tableOfParty, refresh, onSeat, toast }: {
  floor: Floor; now: number; role: Role; tableOfParty: Map<string, Table | undefined>; refresh: () => void;
  onSeat: (t: Table, p: Party) => void; toast: (t: string, k?: Toast["kind"]) => void;
}) {
  const [name, setName] = useState("");
  const [size, setSize] = useState(2);
  const rid = floor.restaurant.id;
  const canEdit = atLeast(role, "host");
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try { await api("POST", `/v1/restaurants/${rid}/waitlist`, { name, party_size: size }); setName(""); }
    catch (err) { toast((err as Error).message, "warn"); }
    refresh();
  };
  const close = async (p: Party, status: string) => { await api("PATCH", `/v1/restaurants/${rid}/waitlist/${p.id}`, { status }); refresh(); };
  return (
    <section className="card" data-testid="waitlist">
      <h2>Waitlist <span className="count">{floor.waitlist.length}</span></h2>
      {canEdit && (
        <form className="row" onSubmit={add}>
          <input aria-label="Party name" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required data-testid="party-name" />
          <input aria-label="Party size" type="number" min={1} max={40} value={size} onChange={(e) => setSize(Number(e.target.value))} data-testid="party-size" />
          <button data-testid="party-add">Add</button>
        </form>)}
      {floor.waitlist.length === 0 && <p className="muted">Nobody is waiting.</p>}
      <ul className="list">
        {floor.waitlist.map((p) => {
          const t = tableOfParty.get(p.id);
          return (
            <li key={p.id} data-testid={`party-${p.name}`}>
              <div>
                <strong>{p.name}</strong> · party of {p.party_size}
                <div className="muted">waiting {duration(now - new Date(p.arrived_at).getTime())}</div>
              </div>
              <div className="row">
                {t && canEdit && <button className="primary" onClick={() => onSeat(t, p)}>Seat at {t.label}</button>}
                {t && !canEdit && <span className="badge ok">{t.label} is ready</span>}
                {canEdit && <button className="link" title="Party left the queue" onClick={() => close(p, "cancelled")}>Remove</button>}
              </div>
            </li>);
        })}
      </ul>
      {!canEdit && <p className="muted">Hosts add parties and confirm seating.</p>}
    </section>
  );
}

function DemoBar({ floor, refresh, toast, reloadMe }: { floor: Floor; refresh: () => void; toast: (t: string, k?: Toast["kind"]) => void; reloadMe: () => void }) {
  const rid = floor.restaurant.id;
  const d = floor.demo;
  const [speed, setSpeed] = useState(2);
  const act = async (body: object) => {
    try { await api("POST", `/v1/restaurants/${rid}/demo/scenario`, body); } catch (e) { toast((e as Error).message, "warn"); }
    refresh();
  };
  const switchRole = async (role: string) => { await api("POST", `/v1/restaurants/${rid}/demo/role`, { role }); reloadMe(); };
  const running = d && !d.done;
  return (
    <section className="demo" data-testid="demo-bar">
      <div className="row">
        <strong>Demo</strong>
        <button className="primary" data-testid="demo-play" onClick={() => act({ action: "start", scenario: "demo_dinner", speed })}>
          {running ? "Restart dinner scenario" : "Play dinner scenario"}
        </button>
        <button data-testid="demo-outage" onClick={() => act({ action: "start", scenario: "demo_outage", speed })}>Camera outage</button>
        {running && <button onClick={() => act({ action: d!.paused ? "resume" : "pause" })}>{d!.paused ? "Resume" : "Pause"}</button>}
        <label className="inline">Speed
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))} data-testid="demo-speed">
            <option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option><option value={10}>10×</option>
          </select>
        </label>
        <button data-testid="demo-reset" onClick={() => act({ action: "reset" })}>Reset</button>
        <span className="spacer" />
        <label className="inline">View as
          <select value={floor.role} onChange={(e) => switchRole(e.target.value)} data-testid="demo-role">
            <option value="admin">Admin</option><option value="host">Host</option><option value="staff">Floor staff</option>
          </select>
        </label>
      </div>
      <p className="note" data-testid="demo-note">
        {d ? `${d.done ? "Finished" : `Step ${d.step} of ${d.steps}`}: ${d.note ?? "…"}`
           : "Press Play. The camera events are replayed into your private copy; you act as the staff."}
      </p>
    </section>
  );
}

function History({ rid, table, onClose }: { rid: string; table: Table; onClose: () => void }) {
  const [rows, setRows] = useState<TableEvent[] | null>(null);
  useEffect(() => { api<TableEvent[]>("GET", `/v1/restaurants/${rid}/tables/${table.id}/events?limit=40`).then(setRows); }, [rid, table.id]);
  const text = (e: TableEvent) =>
    e.to_state ? `${e.from_state ? STATE_LABEL[e.from_state as Table["state"]] : "?"} → ${STATE_LABEL[e.to_state as Table["state"]]}`
      : e.applied ? e.type.replace(/_/g, " ") : `ignored (${(e.reason ?? "").replace(/_/g, " ")})`;
  return (
    <div className="modal" role="dialog" aria-label={`History of ${table.label}`} onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()} data-testid="history">
        <header className="row"><h2>{table.label} history</h2><span className="spacer" /><button onClick={onClose}>Close</button></header>
        {!rows ? <p>Loading…</p> : (
          <table className="data">
            <thead><tr><th>Time</th><th>What happened</th><th>Source</th><th>By</th></tr></thead>
            <tbody>{rows.map((e) => (
              <tr key={e.id} className={e.applied ? "" : "muted"}>
                <td>{new Date(e.observed_at).toLocaleString()}</td><td>{text(e)}</td><td>{e.source}</td><td>{e.actor ?? ""}</td>
              </tr>))}</tbody>
          </table>)}
      </div>
    </div>
  );
}
