import { useEffect, useRef, useState } from "react";

export type Report = {
  orders: { tickets_sent: number; median_kitchen_minutes: number | null; median_ready_to_served_minutes: number | null };
  summary: { from: string; to: string; turns: number; occupancy_pct: number; median_departure_to_ready_minutes: number | null };
  peaks: { timezone: string; by_hour: { weekday: number; hour: number; arrivals: number }[] };
};
type Exchange = { id: string; question: string; answer: string | null; created_at: string; period: string; mode?: string };

export async function request<T>(path: string, method = "GET", body?: object): Promise<T> {
  const response = await fetch(path, {
    method, headers: { "Content-Type": "application/json" }, body: body && JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) {
    throw Object.assign(new Error(typeof result.detail === "string" ? result.detail : "Request failed."), {
      questionSaved: response.headers.get("X-Mise-Question-Saved") === "1",
    });
  }
  return result;
}

const periods = [["week", "This week"], ["month", "This month"], ["year", "This year"], ["custom", "Custom dates"]];
const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function DateRange({ from, to, setFrom, setTo }: {
  from: string; to: string; setFrom: (value: string) => void; setTo: (value: string) => void;
}) {
  return <div className="date-range">
    <label>From<input type="datetime-local" required value={from} onChange={(event) => setFrom(event.target.value)} /></label>
    <label>To<input type="datetime-local" required value={to} onChange={(event) => setTo(event.target.value)} /></label>
    <small>Uses this device’s time zone.</small>
  </div>;
}

export function History({ root }: { root: string }) {
  const [period, setPeriod] = useState("week");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [report, setReport] = useState<Report>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setReport(undefined);
    setError("");
    if (period === "custom" && (!from || !to)) return;
    const query = new URLSearchParams({ period });
    if (period === "custom") {
      query.set("from", new Date(from).toISOString());
      query.set("to", new Date(to).toISOString());
    }
    void request<Report>(root + "/analytics/report?" + query).then((result) => {
      if (active) setReport(result);
    }).catch((err: Error) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [root, period, from, to]);

  const busiest = report?.peaks.by_hour.reduce<Report["peaks"]["by_hour"][number] | undefined>(
    (best, slot) => !best || slot.arrivals > best.arrivals ? slot : best, undefined);
  const peak = busiest?.arrivals ?? 0;
  const arrivals = new Map(report?.peaks.by_hour.map((slot) => [slot.weekday * 24 + slot.hour, slot.arrivals]));
  const fmtDate = (value: string) => new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric", year: "numeric", timeZone: report?.peaks.timezone,
  }).format(new Date(value));
  const timings = [
    ["Kitchen prep", report?.orders.median_kitchen_minutes],
    ["Ready to served", report?.orders.median_ready_to_served_minutes],
    ["Departure to ready", report?.summary.median_departure_to_ready_minutes],
  ] as const;
  const longest = Math.max(1, ...timings.map(([, value]) => value ?? 0));

  return <div className="insights page-enter">
    <div className="report-toolbar">
      <label>Period<select value={period} onChange={(event) => setPeriod(event.target.value)}>
        {periods.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      {report && <span>{fmtDate(report.summary.from)} – {fmtDate(report.summary.to)} · {report.peaks.timezone}</span>}
    </div>
    {period === "custom" && <DateRange from={from} to={to} setFrom={setFrom} setTo={setTo} />}
    {error ? <p className="notice error" role="alert">{error}</p> : !report ? <p role="status">
      {period === "custom" && (!from || !to) ? "Choose a start and end time." : "Loading report…"}
    </p> : <>
      <div className="metrics report-metrics">
        <div><span>Table occupancy</span><strong>{report.summary.occupancy_pct}%</strong><small>Across the selected period</small></div>
        <div><span>Completed turns</span><strong>{report.summary.turns}</strong><small>Recorded departures</small></div>
        <div><span>Kitchen tickets</span><strong>{report.orders.tickets_sent}</strong><small>Sent during this period</small></div>
        <div><span>Median reset time</span><strong>{report.summary.median_departure_to_ready_minutes ?? "—"}</strong><small>Minutes from departure to ready</small></div>
      </div>
      <div className="history-grid">
        <section className="ops-card arrival-card">
          <div className="panel-title"><div><h2>Arrival patterns</h2><p>Table arrivals by weekday and local hour</p></div>
            {busiest && <span className="status-chip">Peak {days[busiest.weekday]} {String(busiest.hour).padStart(2, "0")}:00</span>}
          </div>
          {peak ? <div className="heat-scroll"><table className="heatmap">
            <caption className="sr-only">Number of table arrivals by weekday and local hour</caption>
            <thead><tr><th scope="col">Day</th>{Array.from({ length: 24 }, (_, hour) =>
              <th scope="col" key={hour} title={`${hour}:00`}>{hour % 3 === 0 ? String(hour).padStart(2, "0") : <span className="sr-only">{hour}</span>}</th>)}</tr></thead>
            <tbody>{days.map((day, weekday) => <tr key={day}><th scope="row">{day}</th>
              {Array.from({ length: 24 }, (_, hour) => {
                const count = arrivals.get(weekday * 24 + hour) ?? 0;
                return <td key={hour}><span className="heat-cell" data-level={count ? Math.ceil(count / peak * 4) : 0}
                  title={`${day} ${hour}:00 · ${count} arrivals`}><span className="sr-only">{count}</span></span></td>;
              })}</tr>)}</tbody>
          </table></div> : <div className="report-empty">No arrivals recorded in this period.</div>}
        </section>
        <section className="ops-card timings">
          <div className="panel-title"><div><h2>Service timing</h2><p>Median time per handoff</p></div></div>
          {timings.map(([label, value]) => <div className="timing" key={label}>
            <div><span>{label}</span><strong>{value == null ? "—" : `${value} min`}</strong></div>
            <div className="timing-track">{value != null && <span style={{ width: `${value / longest * 100}%` }} />}</div>
          </div>)}
        </section>
      </div>
    </>}
  </div>;
}

const shortcuts = [
  ["week", "Weekly summary", "Summarize restaurant performance this week."],
  ["month", "Monthly summary", "Summarize restaurant performance this month."],
  ["year", "Yearly summary", "Summarize restaurant performance this year."],
];

export function Assistant({ root }: { root: string }) {
  const [period, setPeriod] = useState("week");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [draft, setDraft] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  const refresh = () => request<Exchange[]>(root + "/analytics/chat").then((rows) => setExchanges([...rows].reverse()));

  useEffect(() => {
    let active = true;
    void request<Exchange[]>(root + "/analytics/chat").then((rows) => {
      if (active) setExchanges([...rows].reverse());
    }).catch((err: Error) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [root]);
  useEffect(() => {
    if (pending || exchanges.length) bottom.current?.scrollIntoView({ block: "nearest" });
  }, [pending, exchanges]);

  async function send(question: string, selectedPeriod: string, mode = "question") {
    if (!question.trim() || inFlight.current) return;
    if (selectedPeriod === "custom" && (!from || !to || from >= to)) {
      setError("Choose a valid start and end time.");
      return;
    }
    inFlight.current = true;
    setPending(question.trim());
    if (mode === "question") setDraft("");
    setError("");
    try {
      await request(root + "/analytics/chat", "POST", {
        question: question.trim(), period: selectedPeriod, mode,
        ...(selectedPeriod === "custom" ? { start: new Date(from).toISOString(), end: new Date(to).toISOString() } : {}),
      });
    } catch (err) {
      const failure = err as Error & { questionSaved?: boolean };
      if (mode === "question" && !failure.questionSaved) setDraft(current => current || question);
      setError(failure.message);
    } finally {
      try { await refresh(); } catch (err) { setError((err as Error).message); }
      inFlight.current = false;
      setPending("");
    }
  }

  return <section className="chat page-enter" aria-label="Restaurant assistant">
    <div className="chat-thread" aria-live="polite">
      {!exchanges.length && !pending && <div className="chat-empty">
        <span className="chat-avatar" aria-hidden>✳</span>
        <h2>What would you like to know?</h2>
        <p>Ask about arrivals, table turnover, or kitchen handoffs.</p>
      </div>}
      {exchanges.map((entry) => <div key={entry.id} className="exchange">
        <p className="chat-question">{entry.question}</p>
        <div className="chat-reply"><span className="chat-avatar" aria-hidden>✳</span><div>
          <strong>{entry.mode === "summary" ? "Saved report" : "Restaurant Assistant"}</strong>
          <p>{entry.answer ?? "This request has no saved answer."}</p>
          <small>{new Date(entry.created_at).toLocaleString()} · {periods.find(([value]) => value === entry.period)?.[1]}</small>
        </div></div>
      </div>)}
      {pending && <div className="exchange"><p className="chat-question">{pending}</p><p className="thinking" role="status">Preparing your answer…</p></div>}
      <div ref={bottom} />
    </div>
    <div className="chat-controls">
      <div className="prompt-row" aria-label="Report shortcuts">{shortcuts.map(([value, label, question]) =>
        <button type="button" key={value} disabled={!!pending} onClick={() => void send(question, value, "summary")}>{label}<span aria-hidden>↗</span></button>)}
      </div>
      {error && <p className="notice error" role="alert">{error}</p>}
      <form className="composer" onSubmit={(event) => { event.preventDefault(); void send(draft, period); }}>
        <textarea aria-label="Question" maxLength={2000} placeholder="Ask about your restaurant…" value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void send(draft, period);
            }
          }} />
        {period === "custom" && <DateRange from={from} to={to} setFrom={setFrom} setTo={setTo} />}
        <div className="composer-tools">
          <select aria-label="Report period" value={period} onChange={(event) => setPeriod(event.target.value)}>
            {periods.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <button className="solid" disabled={!draft.trim() || !!pending}>Send <span aria-hidden>↑</span></button>
        </div>
      </form>
    </div>
  </section>;
}
