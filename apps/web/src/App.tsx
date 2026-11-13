import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, atLeast, Floor, Me } from "./api";
import { Dashboard } from "./Dashboard";
import { Setup } from "./Setup";
import { Analytics } from "./Analytics";

export type Toast = { id: number; text: string; kind: "info" | "warn" };

/** Live floor state: one snapshot, refetched whenever the server says something changed. */
export function useFloor(rid: string, onEvent: (name: string, data: any) => void) {
  const [floor, setFloor] = useState<Floor | null>(null);
  const [connected, setConnected] = useState(false);
  const [offset, setOffset] = useState(0); // server clock minus this device's clock
  const handler = useRef(onEvent);
  handler.current = onEvent;

  const refresh = useCallback(async () => {
    try {
      const f = await api<Floor>("GET", `/v1/restaurants/${rid}/floor`);
      setOffset(new Date(f.server_time).getTime() - Date.now());
      setFloor(f);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 404)) window.location.reload();
    }
  }, [rid]);

  useEffect(() => {
    let timer: number | undefined;
    const soon = () => { window.clearTimeout(timer); timer = window.setTimeout(refresh, 60); };
    refresh();
    const es = new EventSource(`/v1/restaurants/${rid}/stream`);
    es.onopen = () => { setConnected(true); soon(); };  // refetch after every (re)connect
    es.onerror = () => setConnected(false);              // EventSource retries by itself
    const names = ["table.updated", "alert.created", "alert.updated", "alert.renotify", "waitlist.updated",
                   "camera.status", "settings.updated", "demo.progress", "demo.reset"];
    for (const n of names) {
      es.addEventListener(n, (ev) => { handler.current(n, JSON.parse((ev as MessageEvent).data)); soon(); });
    }
    const poll = window.setInterval(refresh, 20000);     // safety net if a stream event is lost
    return () => { es.close(); window.clearInterval(poll); window.clearTimeout(timer); };
  }, [rid, refresh]);

  return { floor, connected, offset, refresh };
}

function Landing({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await fn(); onDone(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <main className="landing">
      <h1>Table Manager</h1>
      <p>A camera notices when a party sits down or leaves. Staff see which tables are ready,
        occupied or need clearing, and the host seats the next party that fits.</p>
      <section className="card">
        <h2>Try the demo</h2>
        <p>You get a private demo restaurant with made-up data. Nothing you do affects other viewers.</p>
        <button className="primary big" data-testid="start-demo" disabled={busy}
                onClick={() => run(() => api("POST", "/v1/demo/sessions"))}>Start demo</button>
      </section>
      <section className="card">
        <h2>Staff sign in</h2>
        <form onSubmit={(e) => { e.preventDefault(); run(() => api("POST", "/v1/auth/login", { email, password })); }}>
          <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
          <button disabled={busy}>Sign in</button>
        </form>
      </section>
      {error && <p className="error" role="alert">{error}</p>}
    </main>
  );
}

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [page, setPage] = useState(window.location.hash || "#/");
  const [sha, setSha] = useState("");
  const load = useCallback(() => {
    api<Me>("GET", "/v1/me").then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => {
    load();
    api("GET", "/healthz").then((h) => setSha(h.git_sha)).catch(() => {});
    const onHash = () => setPage(window.location.hash || "#/");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [load]);

  if (me === undefined) return <main className="landing"><p>Loading…</p></main>;
  if (me === null || me.memberships.length === 0) return <Landing onDone={load} />;
  const m = me.memberships[0];
  return <Shell key={m.restaurant_id + m.role} rid={m.restaurant_id} me={me} page={page} sha={sha} reload={load} />;
}

function Shell({ rid, me, page, sha, reload }: { rid: string; me: Me; page: string; sha: string; reload: () => void }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toast = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);
  const onEvent = useCallback((name: string, data: any) => {
    if (name === "alert.created" && data.type === "needs_clearing") toast(`${data.label} needs clearing`, "warn");
    if (name === "alert.created" && data.type === "greet_reminder") toast(`${data.label}: guests not greeted yet`, "warn");
    if (name === "alert.renotify") toast("A table is still waiting to be cleared", "warn");
    if (name === "demo.reset") toast("Demo reset to the starting state");
  }, [toast]);
  const { floor, connected, offset, refresh } = useFloor(rid, onEvent);
  if (!floor) return <main className="landing"><p>Loading…</p></main>;
  const role = floor.role;
  const logout = async () => { await api("POST", "/v1/auth/logout"); window.location.hash = "#/"; reload(); };

  return (
    <div className="app">
      <header className="top">
        <strong>{floor.restaurant.name}</strong>
        <nav>
          <a href="#/" className={page === "#/" ? "on" : ""}>Floor</a>
          {atLeast(role, "admin") && <a href="#/analytics" className={page === "#/analytics" ? "on" : ""}>Analytics</a>}
          {atLeast(role, "admin") && <a href="#/setup" className={page === "#/setup" ? "on" : ""}>Setup</a>}
        </nav>
        <span className="spacer" />
        <span className={"conn " + (connected ? "ok" : "bad")} data-testid="connection">
          {connected ? "Live" : "Reconnecting…"}
        </span>
        <span className="who" data-testid="role">{me.name} · {role}</span>
        <button className="link" onClick={logout}>Sign out</button>
      </header>
      {page === "#/setup" && atLeast(role, "admin")
        ? <Setup floor={floor} refresh={refresh} toast={toast} />
        : page === "#/analytics" && atLeast(role, "admin")
          ? <Analytics rid={rid} />
          : <Dashboard floor={floor} offset={offset} refresh={refresh} toast={toast} reloadMe={reload} />}
      <footer className="foot">
        <span>build {sha || "dev"}</span>
        <a href="https://github.com/ssartayev/restaurant-ai/actions" target="_blank" rel="noreferrer">Evidence: test results</a>
      </footer>
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={"toast " + t.kind} data-testid="toast">{t.text}</div>)}
      </div>
    </div>
  );
}
