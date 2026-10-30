import { useState } from "react";
import { api, usePoll } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
const errText = (e: unknown) => String(e).replace(/^Error: \d+ /, "").replace(/^\{"detail":"?|"?\}$/g, "");
const fd = (t: number | null) => (t ? new Date(t * 1000).toLocaleDateString() : "–");
const CH: Record<string, string> = { ok: "chip", warn: "chip high", crit: "chip high", info: "chip no_data" };

function Explain({ e }: { e: J }) {
  return <div className="panel"><b>{e.title}</b><span className="muted">{e.plain}</span>
    {e.likely_causes.length > 0 && <span className="muted">Likely causes: {e.likely_causes.join("; ")}.</span>}
    {e.what_to_check.length > 0 && <span className="muted">Check: {e.what_to_check.join("; ")}. ({e.docs})</span>}</div>;
}

function Health() {
  const [h, , reload] = usePoll<J>("/api/diagnostics/health", 15000);
  if (!h) return null;
  return (
    <section className="card">
      <div className="card-head"><h2>System health <span className={`badge ${h.overall === "ok" ? "ok" : ""}`}>{h.overall}</span></h2>
        <button className="pill" onClick={async () => { await api.post("/api/diagnostics/run"); reload(); }}>Check now</button></div>
      <div>{h.components.map((c: J) => <span key={c.name} className={CH[c.status]} title={c.detail}>{c.name}: {c.detail}</span>)}</div>
      <p className="muted">Alerts are raised for critical storage, CPU temperature, clock, database and battery conditions. Thresholds (assumptions you can change): disk ≥ {h.thresholds.disk_min_gb} GB free, CPU warn/critical {h.thresholds.cpu_temp_warn_c}/{h.thresholds.cpu_temp_crit_c} °C.</p>
    </section>
  );
}

function Tasks() {
  const [d, , reload] = usePoll<J>("/api/maintenance", 30000);
  const [sug, , reloadSug] = usePoll<J>("/api/maintenance/suggestions/list", 0);
  const [note, setNote] = useState<Record<string, string>>({});
  const [t, setT] = useState({ title: "", category: "other", interval_days: "30" });
  const [msg, setMsg] = useState("");
  const [log, setLog] = useState<{ id: string; rows: J[] } | null>(null);
  if (!d) return null;
  return (
    <section className="card">
      <h2>Maintenance schedule {d.overdue > 0 && <span className="badge">{d.overdue} overdue</span>}</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Task</th><th>Every</th><th>Last done</th><th>Next due</th><th>Status</th><th /></tr></thead>
        <tbody>{d.tasks.map((x: J) => (
          <tr key={x.id}><td style={{ whiteSpace: "normal" }}>{x.title}</td><td>{x.interval_days} d</td><td>{fd(x.last_done_ts)}</td><td>{fd(x.next_due_ts)} ({x.days_left} d)</td>
            <td><span className={x.status === "ok" ? "chip" : x.status === "disabled" ? "chip no_data" : "chip high"}>{x.status.replace("_", " ")}</span></td>
            <td className="row"><input size={14} placeholder="note" value={note[x.id] ?? ""} onChange={(e) => setNote({ ...note, [x.id]: e.target.value })} />
              <button className="pill" onClick={async () => { await api.post(`/api/maintenance/${x.id}/done`, { note: note[x.id] ?? "" }); setNote({ ...note, [x.id]: "" }); reload(); }}>Done</button>
              <button className="pill" onClick={async () => setLog({ id: x.id, rows: await api.get<J[]>(`/api/maintenance/${x.id}/log`) })}>Log</button>
              <button className="pill" onClick={async () => { await fetch(`/api/maintenance/${x.id}`, { method: "DELETE" }); reload(); reloadSug(); }}>Delete</button></td></tr>))}</tbody>
      </table></div>
      {d.tasks.length === 0 && <p className="muted">No tasks yet.</p>}
      {log && <div className="panel"><b>Log for {log.id}</b>{log.rows.length ? log.rows.map((r, i) => <span key={i} className="muted">{fd(r.ts)}: {r.note || "(no note)"}</span>) : <span className="muted">Nothing recorded.</span>}</div>}
      <h3>Create from my equipment</h3>
      <p className="muted">{sug?.note}</p>
      <ul className="checks">{sug?.suggestions.map((s: J) => <li key={s.id} className="muted">{s.exists ? "✓" : "•"} {s.title} — every {s.interval_days} d</li>)}</ul>
      <button className="primary" onClick={async () => { const r = await api.post<J>("/api/maintenance/suggestions/apply", {}); setMsg(`${r.created.length} task(s) created.`); reload(); reloadSug(); }}>Create the missing tasks</button>
      <h3>Add your own</h3>
      <div className="form">
        <label>Title<input value={t.title} onChange={(e) => setT({ ...t, title: e.target.value })} /></label>
        <label>Category<select value={t.category} onChange={(e) => setT({ ...t, category: e.target.value })}>{d.categories.map((c: string) => <option key={c}>{c}</option>)}</select></label>
        <label>Every (days)<input type="number" value={t.interval_days} onChange={(e) => setT({ ...t, interval_days: e.target.value })} /></label>
      </div>
      <button className="pill" onClick={async () => { try { await api.post("/api/maintenance", { ...t, interval_days: Number(t.interval_days) }); setMsg("Added."); reload(); } catch (e) { setMsg(errText(e)); } }}>Add task</button> <span className="muted">{msg}</span>
    </section>
  );
}

function Replacements() {
  const [rows, , reload] = usePoll<J[]>("/api/maintenance/replacements/list", 0);
  const [r, setR] = useState({ subject_kind: "sensor", subject_id: "", reason: "", old_item: "", new_item: "" });
  const [msg, setMsg] = useState("");
  return (
    <section className="card">
      <h2>Equipment replacement history</h2>
      <div className="table-wrap"><table><thead><tr><th>Date</th><th>Item</th><th>Reason</th><th>Old</th><th>New</th><th /></tr></thead>
        <tbody>{(rows ?? []).map((x) => <tr key={x.id}><td>{fd(x.ts)}</td><td>{x.subject_kind} <code>{x.subject_id}</code></td><td>{x.reason}</td><td>{x.old_item}</td><td>{x.new_item}</td>
          <td><button className="pill" onClick={async () => { await fetch(`/api/maintenance/replacements/${x.id}`, { method: "DELETE" }); reload(); }}>Delete</button></td></tr>)}</tbody></table></div>
      <div className="form">
        <label>Kind<select value={r.subject_kind} onChange={(e) => setR({ ...r, subject_kind: e.target.value })}>{["sensor", "actuator", "tank", "system", "other"].map((k) => <option key={k}>{k}</option>)}</select></label>
        <label>ID<input value={r.subject_id} onChange={(e) => setR({ ...r, subject_id: e.target.value })} /></label>
        <label>Reason<input value={r.reason} onChange={(e) => setR({ ...r, reason: e.target.value })} /></label>
        <label>Old item<input value={r.old_item} onChange={(e) => setR({ ...r, old_item: e.target.value })} /></label>
        <label>New item<input value={r.new_item} onChange={(e) => setR({ ...r, new_item: e.target.value })} /></label>
      </div>
      <button className="pill" onClick={async () => { try { await api.post("/api/maintenance/replacements", r); setMsg("Recorded."); reload(); } catch (e) { setMsg(errText(e)); } }}>Record replacement</button> <span className="muted">{msg}</span>
    </section>
  );
}

function Assistant() {
  const [active] = usePoll<J>("/api/diagnostics/explain/active", 15000);
  const [kind, setKind] = useState("sensor");
  const [id, setId] = useState("");
  const [res, setRes] = useState<J | null>(null);
  const [text, setText] = useState("");
  const [ex, setEx] = useState<J | null>(null);
  const [msg, setMsg] = useState("");
  const [comms] = usePoll<J>("/api/diagnostics/comms", 15000);
  const [sensors] = usePoll<J[]>("/api/sensors", 0);
  return (
    <>
      <section className="card">
        <h2>Troubleshooting assistant</h2>
        <p className="muted">Checks the live system for the likely reason something is not working.</p>
        <div className="row">
          <select value={kind} onChange={(e) => setKind(e.target.value)}><option value="sensor">Sensor</option><option value="output">Output</option><option value="zone">Irrigation zone</option><option value="window">Window</option></select>
          <input list="ids" placeholder="ID" value={id} onChange={(e) => setId(e.target.value)} />
          <datalist id="ids">{kind === "sensor" && (sensors ?? []).map((s) => <option key={s.id} value={s.id} />)}</datalist>
          <button className="primary" disabled={!id} onClick={async () => { try { setRes(await api.post<J>("/api/diagnostics/diagnose", { kind, id })); setMsg(""); } catch (e) { setMsg(errText(e)); } }}>Diagnose</button>
          <span className="muted">{msg}</span></div>
        {res && <div className="panel"><b>{res.verdict}</b>
          {res.findings.map((f: J, i: number) => <span key={i} className={f.status === "problem" ? "" : "muted"}>{f.status === "problem" ? "❌" : f.status === "ok" ? "✅" : "ℹ️"} {f.text}</span>)}
          <b>Next steps</b>{res.next_steps.map((s: string, i: number) => <span key={i} className="muted">→ {s}</span>)}</div>}
        <h3>Explain an error message</h3>
        <div className="row"><input style={{ flex: 1, minWidth: 240 }} placeholder="Paste an error message" value={text} onChange={(e) => setText(e.target.value)} />
          <button className="pill" disabled={!text} onClick={async () => setEx(await api.post<J>("/api/diagnostics/explain", { text }))}>Explain</button></div>
        {ex && <Explain e={ex} />}
      </section>
      <section className="card">
        <h2>Active alerts and recent problems, in plain English</h2>
        {active?.alerts.length === 0 && active?.recent.length === 0 && <p className="muted">Nothing to explain.</p>}
        {active?.alerts.map((a: J) => <div key={a.id}><b>{a.message}</b><Explain e={a.explanation} /></div>)}
        {active?.recent.slice(0, 8).map((r: J, i: number) => <div key={i}><span className="muted">{new Date(r.ts * 1000).toLocaleTimeString()} {r.source}: {r.message}</span><Explain e={r.explanation} /></div>)}
      </section>
      <section className="card">
        <h2>Communication diagnostics</h2>
        <div className="table-wrap"><table><thead><tr><th>Bus / interface</th><th>Sensors</th><th>OK</th><th>Failed</th><th>Success</th></tr></thead>
          <tbody>{comms?.buses.map((b: J) => <tr key={b.bus}><td>{b.bus}</td><td>{b.sensors}</td><td>{b.ok}</td><td>{b.fail}</td><td>{b.success_pct ?? "–"}%</td></tr>)}</tbody></table></div>
        <div className="table-wrap"><table><thead><tr><th>Sensor</th><th>Driver</th><th>OK</th><th>Failed</th><th>Last OK</th><th>ms</th><th>Last error</th></tr></thead>
          <tbody>{comms?.sensors.filter((s: J) => s.fail > 0 || !s.simulated).map((s: J) => <tr key={s.sensor_id}><td><code>{s.sensor_id}</code></td><td>{s.driver}</td><td>{s.ok}</td><td>{s.fail}</td><td>{s.last_ok_age_s ?? "–"}s ago</td><td>{s.last_ms ?? "–"}</td><td style={{ whiteSpace: "normal" }}>{s.last_error ?? ""}</td></tr>)}</tbody></table></div>
        <p className="muted">{comms?.note}</p>
      </section>
    </>
  );
}

export default function MaintenancePage() {
  return (<><Health /><Tasks /><Assistant /><Replacements /></>);
}
