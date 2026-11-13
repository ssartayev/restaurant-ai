import { useEffect, useState } from "react";
import { api, PeakHours, Summary } from "./api";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function Analytics({ rid }: { rid: string }) {
  const [days, setDays] = useState(7);
  const [sum, setSum] = useState<Summary | null>(null);
  const [peak, setPeak] = useState<PeakHours | null>(null);
  useEffect(() => {
    const to = new Date(), from = new Date(to.getTime() - days * 86400000);
    const q = `from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(to.toISOString())}`;
    api<Summary>("GET", `/v1/restaurants/${rid}/analytics/summary?${q}`).then(setSum);
    api<PeakHours>("GET", `/v1/restaurants/${rid}/analytics/peak-hours?${q}`).then(setPeak);
  }, [rid, days]);

  const hours = peak ? [...new Set(peak.by_hour.map((x) => x.hour))].sort((a, b) => a - b) : [];
  const max = peak ? Math.max(1, ...peak.by_hour.map((x) => x.arrivals)) : 1;
  const cell = (d: number, h: number) => peak?.by_hour.find((x) => x.weekday === d && x.hour === h)?.arrivals ?? 0;
  const shifts = peak ? [...new Set(peak.by_shift.map((x) => x.shift))] : [];

  return (
    <main className="page" data-testid="analytics">
      <div className="row">
        <h1>Analytics</h1><span className="spacer" />
        <div className="seg">{[1, 7, 28].map((d) => (
          <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d === 1 ? "Last 24 h" : `Last ${d} days`}</button>))}
        </div>
      </div>
      {!sum ? <p>Loading…</p> : (
        <div className="tiles">
          <div className="tile"><div className="num" data-testid="tile-turns">{sum.turns}</div><div>table turns</div><div className="muted">{sum.turns_per_table} per table</div></div>
          <div className="tile"><div className="num">{sum.occupancy_pct}%</div><div>occupancy</div><div className="muted">share of table-time occupied</div></div>
          <div className="tile"><div className="num">{sum.avg_turn_minutes ?? "–"}<small> min</small></div><div>average turn</div><div className="muted">seated to departed</div></div>
          <div className="tile"><div className="num">{sum.median_departure_to_ready_minutes ?? "–"}<small> min</small></div><div>departure to Ready</div><div className="muted">median of {sum.cleared_count} clearings</div></div>
        </div>)}
      <section className="card">
        <h2>Peak hours</h2>
        <p className="muted">Parties seated per hour, by weekday ({peak?.timezone ?? ""} time). Darker means busier.</p>
        {peak && hours.length === 0 && <p className="muted">No arrivals in this period.</p>}
        {peak && hours.length > 0 && (
          <div className="scroll">
            <table className="heat">
              <thead><tr><th />{hours.map((h) => <th key={h}>{String(h).padStart(2, "0")}</th>)}</tr></thead>
              <tbody>{DAYS.map((name, d) => (
                <tr key={d}><th>{name}</th>{hours.map((h) => {
                  const n = cell(d, h);
                  return <td key={h} style={{ background: `rgba(37, 99, 235, ${n / max * 0.85})`, color: n / max > 0.5 ? "#fff" : undefined }} title={`${name} ${h}:00 – ${n} parties`}>{n || ""}</td>;
                })}</tr>))}
              </tbody>
            </table>
          </div>)}
        {peak && shifts.length > 0 && (
          <table className="data">
            <thead><tr><th>Shift</th>{DAYS.map((d) => <th key={d}>{d}</th>)}</tr></thead>
            <tbody>{shifts.map((s) => (
              <tr key={s}><th>{s}</th>{DAYS.map((_, d) => <td key={d}>{peak.by_shift.find((x) => x.weekday === d && x.shift === s)?.arrivals ?? 0}</td>)}</tr>))}
            </tbody>
          </table>)}
      </section>
    </main>
  );
}
