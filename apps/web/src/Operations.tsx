import { useEffect, useState } from "react";
import { Assistant, History, request } from "./Insights";

type Membership = { restaurant_id: string; restaurant_name: string; role: string };
type Floor = {
  tables: { id: string; label: string; state: string; capacity: number; version: number; tableware_count: number | null; bill_open: boolean }[];
  waitlist: { id: string; name: string; party_size: number }[];
  suggestions: { table_id: string; party_id: string }[];
  cameras: { id: string; name: string; status: string; health: string }[];
  alerts: { id: string; type: string; table_id: string; status: string }[];
  reset_priority: { table_label: string; party_size: number } | null;
};
const pages = { "/": "Live board", "/operations": "Live board", "/kitchen": "Kitchen",
  "/history": "History", "/assistant": "Assistant", "/cameras": "Cameras" };

export function Navigation({ admin }: { admin?: boolean }) {
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    if (admin !== undefined) return;
    void request<{ memberships: Membership[] }>("/v1/me")
      .then(({ memberships }) => setIsAdmin(memberships[0]?.role === "admin"))
      .catch(() => {});
  }, [admin]);
  const links = [["/", "Live board"], ["/kitchen", "Kitchen"], ["/recordings", "Recordings"],
                 ...((admin ?? isAdmin) ? [["/history", "History"], ["/assistant", "Assistant"], ["/cameras", "Cameras"]] : [])];
  return <nav className="product-nav" aria-label="Main navigation">
    <a href="/" className="wordmark"><span className="brand-symbol" aria-hidden="true"><i /><i /><i /><i /></span><span className="brand-name">mise<span className="brand-dot">.</span><small>THE SERVICE OF FLOW</small></span></a>
    <div>{links.map(([path, name]) => <a href={path} key={path}
      aria-current={(window.location.pathname === path || (path === "/" && window.location.pathname === "/operations")) ? "page" : undefined}>{name}</a>)}</div>
  </nav>;
}
type Ticket = { id: string; table_label: string; status: string; items: { name: string; quantity: number }[] };
export function Operations() {
  const [membership, setMembership] = useState<Membership>();
  const [floor, setFloor] = useState<Floor>();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const tab = pages[window.location.pathname as keyof typeof pages] ?? "Live board";
  const [pairing, setPairing] = useState<{ id: string; device_token: string }>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const root = membership ? `/v1/restaurants/${membership.restaurant_id}` : "";
  const admin = membership?.role === "admin";
  const loadMembership = () => request<{ memberships: Membership[] }>("/v1/me")
    .then((me) => setMembership(me.memberships[0]));
  useEffect(() => { void loadMembership().catch(() => {}); }, []);
  useEffect(() => {
    if (!root) return;
    let active = true;
    const refresh = () => {
      void Promise.all([request<Floor>(root + "/floor"), request<Ticket[]>(root + "/orders")])
        .then(([nextFloor, nextTickets]) => { if (active) { setFloor(nextFloor); setTickets(nextTickets); } })
        .catch((err: Error) => { if (active) setError(err.message); });
    };
    refresh();
    const stream = new EventSource(root + "/stream");
    for (const name of ["table.updated", "camera.status", "order.updated", "alert.created", "alert.updated", "waitlist.updated"]) {
      stream.addEventListener(name, refresh);
    }
    stream.onopen = refresh;
    const timer = window.setInterval(refresh, 5000);
    return () => { active = false; stream.close(); window.clearInterval(timer); };
  }, [root, refreshKey]);
  async function act(task: () => Promise<unknown>) {
    setError("");
    setBusy(true);
    try { await task(); setRefreshKey((key) => key + 1); } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  return <main className="ops">
    <Navigation admin={admin} />
    <header className="page-heading page-enter"><div><p>{membership?.restaurant_name ?? "Restaurant operations"}</p><h1>{tab}</h1></div>
      {membership && <button onClick={() => void act(async () => { await request("/v1/auth/logout", "POST"); window.location.assign("/"); })}>Sign out</button>}
    </header>
    {error && <p role="alert">{error}</p>}
    {!membership ? <section className="ops-card">
      <h2>Staff sign-in</h2>
      <form onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        void act(async () => { await request("/v1/auth/login", "POST", { email: data.get("email"), password: data.get("password") }); await loadMembership(); });
      }}>
        <label>Email<input name="email" type="email" required /></label>
        <label>Password<input name="password" type="password" required /></label>
        <button disabled={busy}>Sign in</button>
      </form>
      <button className="demo-start" disabled={busy} onClick={() => void act(async () => { await request("/v1/demo/sessions", "POST"); await loadMembership(); })}>Start sample restaurant</button>
    </section> : <>
      {!admin && ["History", "Assistant", "Cameras"].includes(tab) && <p>Administrator access required.</p>}
      {tab === "Live board" && <div className="live-board page-enter">
        <div className="metrics">{["occupied", "ready", "needs_clearing"].map((state) =>
          <div key={state} data-state={state}><strong>{floor?.tables.filter((table) => table.state === state).length ?? "—"}</strong><span>{state.replace("_", " ")}</span></div>)}
          <div><strong>{floor?.waitlist.length ?? "—"}</strong><span>Waiting parties</span></div>
        </div>
        <div className="service-layout">
        <section className="ops-card">
          <div className="panel-title"><h2>Dining room</h2>
            <span className="status-chip">{floor?.cameras.filter((camera) => camera.status === "online" && camera.health === "ok").length ?? 0} healthy cameras</span>
          </div>
          {floor?.reset_priority && <p className="priority"><strong>Reset {floor.reset_priority.table_label} first.</strong> It fits a waiting party of {floor.reset_priority.party_size}.</p>}
          {floor?.alerts.filter((alert) => alert.type === "bill_check").map((alert) => <p className="priority" key={alert.id}>
            {floor.tables.find((table) => table.id === alert.table_id)?.label} · Check open bill after extended vacancy.
            {alert.status === "open" && <button disabled={busy} onClick={() => void act(() => request(root + "/alerts/" + alert.id + "/ack", "POST"))}>Acknowledge</button>}
          </p>)}
          <div className="live-tables">{floor?.tables.map((table) => <article key={table.id} className="ticket">
            <strong>{table.label}</strong><span className="table-status" data-state={table.state}>{table.state.replace("_", " ")}</span>
            <small>{table.capacity} seats{table.tableware_count ? ` · ${table.tableware_count} items detected` : ""}</small>
            {table.state === "needs_clearing" && !!table.tableware_count && <strong className="clearing-hint">Check dishes</strong>}
            {table.state === "needs_clearing" && <button disabled={busy} onClick={() => void act(() => request(root + "/tables/" + table.id + "/commands", "POST", { command: "mark_ready", expected_version: table.version }))}>Mark ready</button>}
            {table.state === "occupied" && <button disabled={busy} onClick={() => void act(() => request(root + "/tables/" + table.id + "/commands", "POST", { command: "mark_needs_clearing", expected_version: table.version }))}>Party left</button>}
            {table.state === "ready" && !table.bill_open && <button disabled={busy} onClick={() => void act(() => request(root + "/tables/" + table.id + "/commands", "POST", { command: "mark_occupied", expected_version: table.version }))}>Mark occupied</button>}
            {table.bill_open && membership.role !== "staff" && <button disabled={busy} onClick={() => void act(() => request(root + "/tables/" + table.id + "/bill/paid", "POST"))}>Mark bill paid</button>}
          </article>)}</div>
        </section>
        <div className="service-side">
        {membership.role !== "staff" && <section className="ops-card">
          <h2>Waiting parties</h2>
          <form onSubmit={(event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const data = new FormData(form);
            void act(async () => {
              await request(root + "/waitlist", "POST", { name: data.get("name"), party_size: Number(data.get("size")) });
              form.reset();
            });
          }}>
            <label>Party name<input name="name" maxLength={100} required /></label>
            <label>Party size<input name="size" type="number" min="1" max="40" defaultValue="2" required /></label>
            <button disabled={busy}>Add party</button>
          </form>
          {floor?.waitlist.map((party) => {
            const match = floor.suggestions.find((suggestion) => suggestion.party_id === party.id);
            const table = floor.tables.find((entry) => entry.id === match?.table_id);
            return <p key={party.id}>{party.name ?? "Walk-in"} · {party.party_size} {table &&
              <button disabled={busy} onClick={() => void act(() => request(root + "/tables/" + table.id + "/seat", "POST",
                { party_id: party.id, expected_version: table.version }))}>Seat at {table.label}</button>}</p>;
          })}
        </section>}
        <section className="ops-card">
          <h2>Send a table order</h2>
          <form onSubmit={(event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const data = new FormData(form);
            const name = String(data.get("item")).trim();
            if (!name) return;
            void act(async () => {
              await request(root + "/orders", "POST", { table_id: data.get("table"), items: [{ name, quantity: Number(data.get("quantity")) }] });
              form.reset();
              window.location.assign("/kitchen");
            });
          }}>
            <label>Table<select name="table" required>{floor?.tables.map((table) => <option key={table.id} value={table.id}>{table.label} · {table.capacity} seats</option>)}</select></label>
            <label>Dish<input name="item" required maxLength={100} /></label>
            <label>Quantity<input name="quantity" type="number" min="1" max="100" defaultValue="1" required /></label>
            <button disabled={busy || !floor?.tables.length}>Send to kitchen</button>
          </form>
        </section>
        </div>
        </div>
      </div>}
      {tab === "Kitchen" && <section className="ops-card"><h2>Kitchen tickets</h2>
        {!tickets.length && <p>No open tickets.</p>}
        {tickets.map((ticket) => {
          const next = { sent: "preparing", preparing: "ready", ready: "served" }[ticket.status];
          return <article key={ticket.id} className="ticket">
            <strong>{ticket.table_label} · {ticket.status}</strong>
            <p>{ticket.items.map((item) => `${item.quantity} × ${item.name}`).join(", ")}</p>
            {next && <button disabled={busy} onClick={() => void act(async () => {
              await request(root + "/orders/" + ticket.id, "PATCH", { status: next });
              setTickets(await request<Ticket[]>(root + "/orders"));
            })}>Mark {next}</button>}
          </article>;
        })}
      </section>}
      {tab === "History" && admin && <History root={root} />}
      {tab === "Assistant" && admin && <Assistant root={root} />}
      {tab === "Cameras" && admin && <section className="camera-setup page-enter">
        <div className="setup-intro"><span className="eyebrow">CONNECTED SERVICE</span><h2>A room that stays in sync.</h2><p>Set up your tables, connect a camera, then map the seats. Your team stays in control.</p><div className="setup-path"><span>01 Tables</span><b>→</b><span>02 Cameras</span><b>→</b><span>03 Seat zones</span></div></div>
        <div className="setup-grid"><section className="ops-card setup-panel"><span className="step-number">01 / THE ROOM</span><h2>Make room for everyone.</h2><p className="note">Give each table a name your team recognizes.</p>
        <form onSubmit={(event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const data = new FormData(form);
          void act(async () => {
            await request(root + "/tables", "POST", { label: data.get("label"), capacity: Number(data.get("capacity")) });
            form.reset();
          });
        }}>
          <label>Table number<input name="label" maxLength={32} required /></label>
          <label>Seats<input name="capacity" type="number" min="1" max="40" required /></label>
          <button disabled={busy}>Add table</button>
        </form>
        </section><section className="ops-card setup-panel"><span className="step-number">02 / THE CONNECTION</span><h2>Eyes on the dining room.</h2><div className="camera-list">{floor?.cameras.map((camera) => <div className="camera-item" key={camera.id}><span className="camera-glyph" aria-hidden="true">◉</span><div><strong>{camera.name}</strong><small>{camera.health === "ok" ? "Image quality OK" : camera.health}</small></div><span className="connection-state" data-online={camera.status === "online"}>{camera.status}</span></div>)}</div>
        <form onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          void act(async () => setPairing(await request(root + "/cameras", "POST", { name: data.get("name") })));
        }}>
          <label>Camera name<input name="name" required maxLength={100} /></label><button disabled={busy}>Add camera</button>
        </form>
        {pairing && <p className="pairing-note">Save this device token in a private file on the camera worker. <code>{pairing.device_token}</code></p>}
        </section></div><section className="ops-card zone-panel"><span className="step-number">03 / THE SEAT MAP</span><h2>Tell the camera where to look.</h2><p className="note">Match each table to its seating area. Coordinates run from 0 to 1 across the image.</p>
        <form onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          void act(async () => {
            const left = Number(data.get("left")), top = Number(data.get("top"));
            const right = Number(data.get("right")), bottom = Number(data.get("bottom"));
            if (left >= right || top >= bottom) throw Error("Right and bottom must be greater than left and top.");
            await request(root + "/tables/" + data.get("table") + "/zone", "PUT", {
              camera_id: data.get("camera"), polygons: [[[left, top], [right, top], [right, bottom], [left, bottom]]],
            });
            setPairing(undefined);
          });
        }}>
          <label>Camera<select name="camera" required>{floor?.cameras.map((camera) => <option key={camera.id} value={camera.id}>{camera.name}</option>)}</select></label>
          <label>Table<select name="table" required>{floor?.tables.map((table) => <option key={table.id} value={table.id}>{table.label}</option>)}</select></label>
          {["left", "top", "right", "bottom"].map((edge) => <label key={edge}>{edge}<input name={edge} type="number" step=".01" min="0" max="1" required /></label>)}
          <button disabled={busy}>Save camera zone</button>
        </form>
        <small className="zone-tip">Map the seats carefully to reduce passers-by being counted as guests. Visual zone drawing is a planned improvement.</small></section>
      </section>}
    </>}
  </main>;
}
