import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./video.css";
import { matchStaff, staffTracks, StaffMark } from "./staffTracking";
import { Navigation, Operations } from "./Operations";

type Table = { id: number; x: number; y: number; box: [number, number, number, number]; manual?: boolean };
type Reading = { tableware_count?: number; state: string; people: number; since: number };
type ObjectDetection = { box: [number, number, number, number]; label: string; kind: string; confidence: number; reason?: string; appearance?: number[]; track?: number };
type Analysis = { id?: string; tables: Table[]; timeline: [number, Reading[]][]; objects?: [number, ObjectDetection[]][] };

function clock(seconds: number) {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function CameraReview({ path, onActive }: { path: string; onActive: (active: boolean) => void }) {
  const board = path === "/" || path === "/operations";
  const [staffMarks, setStaffMarks] = useState<StaffMark[]>([]);
  const [personSelection, setPersonSelection] = useState<StaffMark>();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [file, setFile] = useState<File>();
  const [url, setUrl] = useState("");
  const [analysis, setAnalysis] = useState<Analysis>();
  const [message, setMessage] = useState("");
  const [names, setNames] = useState<Record<number, string>>({});
  const [positions, setPositions] = useState<Record<number, { x: number; y: number }>>({});
  const [selected, setSelected] = useState<number>();
  const [greeted, setGreeted] = useState<Record<number, number>>({});
  const [capacity, setCapacity] = useState<Record<number, number>>({});
  const [queue, setQueue] = useState<{ id: string; name: string; size: number }[]>([]);
  const [assigned, setAssigned] = useState<Record<number, number>>({});
  const drag = useRef<number | null>(null);
  const [readyAt, setReadyAt] = useState<Record<number, number>>({});
  const [time, setTime] = useState(0);
  const [view, setView] = useState<"camera" | "floor">("camera");
  const [ratio, setRatio] = useState(16 / 9);
  const [adding, setAdding] = useState(false);

  // Corrections (tables added or removed, people marked as staff) are sent back to the
  // server, which recomputes occupancy from the evidence it kept for this analysis.
  const recompute = async (nextTables: Table[], marks: StaffMark[]) => {
    if (!analysis?.id) return;
    const body = { tables: nextTables.map(({ id, box, manual }) => ({ id, box, manual: !!manual })),
      staff_tracks: staffTracks(analysis.objects ?? [], marks) };
    const response = await fetch(`/analyze/${analysis.id}/recompute`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      setMessage(typeof error.detail === "string" ? error.detail : "Could not update the analysis.");
      return;
    }
    const result = await response.json() as Pick<Analysis, "tables" | "timeline">;
    setAnalysis((current) => current && current.id === analysis.id ? { ...current, tables: result.tables, timeline: result.timeline } : current);
    setMessage("");
  };
  const updateMarks = (marks: StaffMark[]) => { setStaffMarks(marks); void recompute(analysis?.tables ?? [], marks); };

  useEffect(() => {
    setView(board ? "floor" : "camera");
    if (!board && path !== "/recordings") videoRef.current?.pause();
  }, [path, board]);

  useEffect(() => {
    if (!file) return;
    onActive(true);
    const objectUrl = URL.createObjectURL(file);
    const request = new AbortController();
    setUrl(objectUrl);
    setAnalysis(undefined);
    setStaffMarks([]);
    setPersonSelection(undefined);
    setTime(0);
    setReadyAt({});
    setNames({});
    setPositions({});
    setSelected(undefined);
    setGreeted({});
    setCapacity({});
    setQueue([]);
    setAssigned({});
    setView("camera");
    setAdding(false);
    setMessage("Analyzing the recording…");
    const form = new FormData();
    form.append("video", file);
    fetch("/analyze", { method: "POST", body: form, signal: request.signal })
      .then(async (response) => {
        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(error.detail || "Analysis failed. Check the local server.");
        }
        return response.json() as Promise<Analysis>;
      })
      .then((result) => {
        if (request.signal.aborted) return;
        setAnalysis(result);
        setMessage(result.tables.length ? "" : "No tables were found automatically. Use “Add a missing table” and click each table in the video.");
      })
      .catch((error: Error) => {
        if (!request.signal.aborted) setMessage(error.message);
      });
    return () => {
      request.abort();
      URL.revokeObjectURL(objectUrl);
    };
  }, [file]);

  const timeline = analysis?.timeline ?? [];
  const tables = analysis?.tables ?? [];
  const staffMatches = useMemo(() => matchStaff(analysis?.objects ?? [], staffMarks), [analysis, staffMarks]);
  let index = Math.min(timeline.length - 1, Math.floor(time));
  while (index + 1 < timeline.length && timeline[index + 1][0] <= time) index++;
  while (index > 0 && timeline[index][0] > time) index--;
  const states = timeline[index]?.[1] ?? [];
  const occupied = states.filter(({ state }) => state === "occupied").length;
  const isReady = (table: Table, reading?: Reading) =>
    reading?.state === "vacant" && assigned[table.id] !== reading.since && readyAt[table.id] >= reading.since && readyAt[table.id] <= time;
  const nameOf = (id: number) => names[id]?.trim() || `T${id}`;
  const active = tables.find((table) => table.id === selected);
  const departed = states.map((reading, i) => reading.state === "vacant" &&
    timeline.some(([at, rows]) => at < reading.since && rows[i]?.state === "occupied"));
  const selectedReading = active ? states[tables.indexOf(active)] : undefined;
  const suggestions = tables.flatMap((table, i) => {
    if (!isReady(table, states[i]) || assigned[table.id] === states[i].since) return [];
    const party = queue.find((entry) => entry.size <= (capacity[table.id] ?? 0));
    return party ? [{ table, party }] : [];
  }).sort((a, b) => queue.indexOf(a.party) - queue.indexOf(b.party) ||
    capacity[a.table.id] - capacity[b.table.id]);
  const next = suggestions[0];
  const people = states.reduce((sum, reading) => sum + reading.people, 0);
  const elapsedTimeline = timeline.filter(([at]) => at <= time);
  const peak = elapsedTimeline.reduce((max, [, readings]) =>
    Math.max(max, readings.reduce((sum, reading) => sum + reading.people, 0)), 0);

  const totals = tables.map(() => ({ occupiedSeconds: 0, peak: 0 }));
  elapsedTimeline.forEach(([sampleTime, readings], sampleIndex) => {
    // Bound the final partial interval by playback time, and never fill long evidence gaps.
    const nextTime = Math.min(time, timeline[sampleIndex + 1]?.[0] ?? time, sampleTime + 2);
    readings.forEach((reading, tableIndex) => {
      const total = totals[tableIndex];
      if (reading.state === "occupied") total.occupiedSeconds += nextTime - sampleTime;
      total.peak = Math.max(total.peak, reading.people);
    });
  });

  const busiest = elapsedTimeline.find(([, readings]) => readings.reduce((sum, reading) => sum + reading.people, 0) === peak);

  return <main>
    <Navigation />
    <header className="page-heading"><div><p>SEE THE SERVICE, FRAME BY FRAME</p><h1>{board ? "Live board" : "Recording review"}</h1></div><label className="upload"><span className="upload-icon" aria-hidden="true">↥</span><span><strong>Choose recording</strong><small>{file?.name ?? "Upload a restaurant video"}</small></span>
      <input aria-label="Choose recording" type="file" accept="video/*" onChange={(event) => setFile(event.currentTarget.files?.[0])} />
    </label></header>
    {file && <div className="footage-source"><div><strong>Active source: {file.name}</strong><small>Recording playback · {clock(time)} · This board follows the video, not the sample restaurant. Restaurant orders and saved History remain separate.</small></div>
      <button onClick={() => { videoRef.current?.pause(); setFile(undefined); setAnalysis(undefined); setUrl(""); onActive(false); }}>Close footage</button>
    </div>}
    {message && <p role="status">{message}</p>}
    {analysis && <div className="metrics">
      <div><strong>{tables.length}</strong><span>Tables</span></div>
      <div><strong>{occupied}</strong><span>Occupied</span></div>
      <div><strong>{tables.filter((table, i) => isReady(table, states[i])).length}</strong><span>Ready</span></div>
      <div><strong>{people}</strong><span>Estimated diners</span></div>
    </div>}
    {analysis && <nav className="views" aria-label="Recording view">
      <button aria-pressed={view === "camera"} onClick={() => { setView("camera"); setAdding(false); }}>Camera</button>
      <button aria-pressed={view === "floor"} onClick={() => { setView("floor"); setAdding(false); }}>2D floor plan</button>
      {view === "camera" && <button className="add-table" aria-pressed={adding} onClick={() => { videoRef.current?.pause(); setAdding(!adding); }}>
        {adding ? "Cancel adding" : "Add a missing table"}</button>}
    </nav>}
    {adding && <p className="note" role="status">Click the middle of a table in the video. You can add several; press “Cancel adding” when done.</p>}
    <div className="workspace">
    <section>
    {url ? <div className={view === "camera" ? "camera" : "floor-view"} style={{ aspectRatio: ratio }}>
      <video ref={videoRef} key={url} className={view === "floor" ? "floor-player" : undefined} src={url} controls muted playsInline
        onLoadedMetadata={({ currentTarget: video }) => {
          if (video.videoHeight) setRatio(video.videoWidth / video.videoHeight);
        }}
        onTimeUpdate={({ currentTarget: video }) => setTime(video.currentTime)}
        onSeeking={({ currentTarget: video }) => setTime(video.currentTime)}
        onSeeked={({ currentTarget: video }) => setTime(video.currentTime)} />
      {view === "camera" && (analysis?.objects?.[index]?.[1] ?? []).map((object, objectIndex) => {
        const [left, top, right, bottom] = object.box;
        return <div className="object-box" data-kind={object.kind} key={objectIndex}
          style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${(right-left)*100}%`, height: `${(bottom-top)*100}%` }}>
          {object.kind === "person" ? <button className="person-label" aria-label={`Select person ${objectIndex + 1}`}
            onClick={() => { videoRef.current?.pause(); setPersonSelection({ sample: index, object: objectIndex }); }}>
            {staffMatches.has(index + ":" + objectIndex) ? "Waiter · staff marked" : object.label}
          </button> : <span title={object.reason}>{object.label} · {Math.round(object.confidence * 100)}%</span>}
        </div>;
      })}
      {adding && view === "camera" && <div className="add-table-layer" aria-label="Click a table to add it"
        onClick={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect();
          const x = (event.clientX - bounds.left) / bounds.width, y = (event.clientY - bounds.top) / bounds.height;
          // Size a new table like the ones already found; otherwise a typical four-top.
          const sizes = tables.map(({ box }) => [box[2] - box[0], box[3] - box[1]]);
          const middle = (values: number[], fallback: number) => values.length ? [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)] : fallback;
          const w = middle(sizes.map(([width]) => width), .16), h = middle(sizes.map(([, height]) => height), .2);
          const clamp = (value: number) => Math.min(1, Math.max(0, value));
          const box: Table["box"] = [clamp(x - w / 2), clamp(y - h / 2), clamp(x + w / 2), clamp(y + h / 2)];
          const id = Math.max(0, ...tables.map((table) => table.id)) + 1;
          void recompute([...tables, { id, x, y, box, manual: true }], staffMarks);
          setSelected(id);
        }} />}
      {tables.map((table, i) => {
        const reading = states[i];
        const state = reading?.state === "vacant" && assigned[table.id] === reading.since ? "assigned"
          : isReady(table, reading) ? "ready" : reading?.state === "vacant" && reading.tableware_count ? "check" : departed[i] ? "check" : reading?.state ?? "unknown";
        const position = view === "floor" ? positions[table.id] ?? table : table;
        return <button type="button" key={table.id} className={`table-marker ${state}`}
          aria-pressed={selected === table.id}
          onClick={() => setSelected(table.id)}
          onPointerDown={(event) => {
            if (view !== "floor" || event.button !== 0) return;
            drag.current = table.id;
            event.currentTarget.setPointerCapture(event.pointerId);
            setSelected(table.id);
          }}
          onPointerMove={(event) => {
            if (view !== "floor" || drag.current !== table.id) return;
            const bounds = event.currentTarget.parentElement!.getBoundingClientRect();
            const clamp = (value: number) => Math.min(.94, Math.max(.06, value));
            setPositions((current) => ({ ...current, [table.id]: {
              x: clamp((event.clientX - bounds.left) / bounds.width),
              y: clamp((event.clientY - bounds.top) / bounds.height),
            } }));
          }}
          onLostPointerCapture={() => { drag.current = null; }}
          onKeyDown={(event) => {
            if (view !== "floor") return;
            const delta = { ArrowLeft: [-.02, 0], ArrowRight: [.02, 0], ArrowUp: [0, -.02], ArrowDown: [0, .02] }[event.key];
            if (!delta) return;
            event.preventDefault();
            setPositions({ ...positions, [table.id]: {
              x: Math.min(.94, Math.max(.06, position.x + delta[0])),
              y: Math.min(.94, Math.max(.06, position.y + delta[1])),
            } });
          }}
          style={{ left: `${position.x * 100}%`, top: `${position.y * 100}%` }}>
          <strong>{nameOf(table.id)}</strong>{view === "floor" && ` · ${state}`}
          {view === "floor" && state === "check" && !!reading?.tableware_count && ` · ${reading.tableware_count} items`}
          {view === "floor" && reading?.state === "occupied" && ` · ${reading.people} · ${clock(time - reading.since)}`}
        </button>;
      })}
    </div> : <div className="empty recording-empty"><div><span className="empty-orbit" aria-hidden="true">↗</span><p className="eyebrow">A NEW PERSPECTIVE ON SERVICE</p><h2>Your dining room. In focus.</h2><p>Choose a fixed-camera restaurant recording to begin.</p><div className="empty-steps"><span>01 Upload</span><span>02 Analyze</span><span>03 Explore the floor</span></div></div></div>}
    {analysis && <section className="ops-card staff-identification">
      <h2>Identify waiters</h2>
      <p>Click a person’s label to pause and select them, then mark them. The label follows that person through the recording, and they stop counting as a diner. If they are hidden for a long time or cross someone in the same uniform, the label stops rather than jump to the wrong person: mark them again.</p>
      {personSelection && <button onClick={() => { updateMarks([...staffMarks.filter(mark => mark.sample !== personSelection.sample || mark.object !== personSelection.object), personSelection]); setPersonSelection(undefined); }}>Mark selected person as waiter</button>}
      {staffMarks.length > 0 && <button onClick={() => { updateMarks([]); setPersonSelection(undefined); }}>Clear waiter marks</button>}
      <small>{staffMarks.length} manual marks · {Array.from(staffMatches).filter(key => key.startsWith(index + ":")).length} matched in this frame. Marks stay in this recording session only.</small>
      <p className="note">Marked staff are left out of table occupancy and diner counts for this recording.</p>
    </section>}
    {view === "camera" && analysis && <p className="note">Detection boxes are shown about once per second; people are followed several times a second in between. Guest/waiter labels are behavioral estimates, not verified roles. Uncertain people remain unclassified; cleanliness is not verified.</p>}
    {view === "floor" && <p className="note">Drag tables to arrange the floor plan. Select a table to edit its number.</p>}
    {tables.length > 0 && <details open className="playback-statistics" data-playback-time={time}>
      <summary>Recording statistics · up to {clock(time)}</summary>
      <p className="note">Synchronized to playback. Pausing freezes the totals; seeking recalculates them. Gaps longer than two seconds are not counted as continuous evidence.</p>
      <p>Peak seated so far: {peak}{peak > 0 && busiest && ` at ${clock(busiest[0])}`}</p>
      <table>
        <thead><tr><th>Table</th><th>Occupied time</th><th>Peak seated</th><th>Table readiness</th></tr></thead>
        <tbody>{tables.map((table, i) => <tr key={table.id}>
          <th scope="row">{nameOf(table.id)}</th><td>{clock(totals[i].occupiedSeconds)}</td><td>{totals[i].peak}</td>
          <td>{isReady(table, states[i])
            ? `Ready · ${clock(readyAt[table.id] - states[i].since)} after vacancy`
            : states[i]?.state === "vacant" && assigned[table.id] !== states[i].since
              ? <button onClick={() => setReadyAt({ ...readyAt, [table.id]: time })}>Mark ready</button>
              : "—"}</td>
        </tr>)}</tbody>
      </table>
    </details>}
    {tables.length > 0 && <p className="note">Counts are estimates. Table cleanliness is unverified.</p>}
    </section>
    {tables.length > 0 && <aside className="staff">
      {active && <section>
        <h2>{nameOf(active.id)}</h2>
        {selectedReading?.state === "vacant" && !isReady(active, selectedReading) &&
          assigned[active.id] !== selectedReading.since &&
          <button className="primary-action" onClick={() => setReadyAt({ ...readyAt, [active.id]: time })}>Mark ready</button>}
        {selectedReading?.state === "occupied" &&
          !(greeted[active.id] >= selectedReading.since && greeted[active.id] <= time) &&
          <button className="primary-action" onClick={() => setGreeted({ ...greeted, [active.id]: time })}>Mark greeted</button>}
        <label>Table number<input value={names[active.id] ?? `T${active.id}`} maxLength={16}
          onChange={(event) => setNames({ ...names, [active.id]: event.target.value })} /></label>
        <label>Seats<input type="number" min="1" max="100" value={capacity[active.id] ?? ""}
          onChange={(event) => setCapacity({ ...capacity, [active.id]: event.target.valueAsNumber || 0 })} /></label>
        <button className="remove-table" onClick={() => { void recompute(tables.filter((table) => table.id !== active.id), staffMarks); setSelected(undefined); }}>
          Remove this table{active.manual ? " (added by hand)" : " (not a real table)"}</button>
      </section>}
      <section aria-label="Staff alerts">
        <h2>Staff alerts</h2>
      {tables.map((table, i) => {
          const reading = states[i];
          if (reading?.state === "occupied" && time - reading.since >= 60 &&
              !(greeted[table.id] >= reading.since && greeted[table.id] <= time)) return <p key={table.id}>
            {nameOf(table.id)} · Check greeting <button onClick={() => setGreeted({ ...greeted, [table.id]: time })}>Greeted</button>
          </p>;
          if (departed[i] && assigned[table.id] !== reading.since && !isReady(table, reading)) return <p key={table.id}>
            {nameOf(table.id)} · Check and reset <button onClick={() => setReadyAt({ ...readyAt, [table.id]: time })}>Mark ready</button>
          </p>;
          return null;
        })}
        <small>Greeting checks appear after one minute of estimated occupancy.</small>
      </section>
      <section>
        <h2>Waitlist</h2>
        <form onSubmit={(event) => {
          event.preventDefault();
          const form = event.currentTarget;
          const data = new FormData(form);
          const name = String(data.get("party") ?? "").trim();
          if (!name) return;
          setQueue([...queue, { id: crypto.randomUUID(), name, size: Number(data.get("size")) }]);
          form.reset();
        }}>
          <label>Party name<input name="party" required maxLength={40} /></label>
          <label>Party size<input name="size" required type="number" min="1" max="100" defaultValue="2" /></label>
          <button>Add party</button>
        </form>
        <ol>{queue.map((party) => <li key={party.id}>{party.name} · {party.size}</li>)}</ol>
        {next ? <p>{next.party.name} fits {nameOf(next.table.id)}. <button onClick={() => {
          setAssigned({ ...assigned, [next.table.id]: states[tables.indexOf(next.table)].since });
          setQueue(queue.filter((party) => party.id !== next.party.id));
        }}>Confirm seating</button></p> : <small>Set seat counts and mark a table ready to get a suggestion.</small>}
      </section>
    </aside>}
    </div>
  </main>;
}

function Workspace() {
  const [path, setPath] = useState(window.location.pathname);
  const [hasFootage, setHasFootage] = useState(false);
  useEffect(() => {
    const pop = () => setPath(window.location.pathname);
    const navigate = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = (event.target as Element).closest("a");
      if (!link || link.target || link.hasAttribute("download")) return;
      const url = new URL(link.href);
      if (url.origin !== location.origin || !["/", "/operations", "/recordings", "/kitchen", "/history", "/assistant", "/cameras"].includes(url.pathname)) return;
      event.preventDefault();
      history.pushState(null, "", url.pathname);
      setPath(url.pathname);
      window.scrollTo(0, 0);
    };
    window.addEventListener("popstate", pop);
    document.addEventListener("click", navigate);
    return () => { window.removeEventListener("popstate", pop); document.removeEventListener("click", navigate); };
  }, []);
  const showFootage = path === "/recordings" || (hasFootage && ["/", "/operations"].includes(path));
  return <>
    <div hidden={!showFootage}><CameraReview path={path} onActive={setHasFootage} /></div>
    {!showFootage && <Operations key={path} />}
  </>;
}
createRoot(document.getElementById("root")!).render(<Workspace />);
