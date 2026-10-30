import { useState } from "react";
import { api, usePoll } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
const errText = (e: unknown) => String(e).replace(/^Error: \d+ /, "").replace(/^\{"detail":"?|"?\}$/g, "");
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const fmtTs = (t: number | null) => (t ? new Date(t * 1000).toLocaleString() : "–");

function useAct() {
  const [msg, setMsg] = useState("");
  const act = async (fn: () => Promise<unknown>, ok = "Done.") => {
    try { await fn(); setMsg(ok); } catch (e) { setMsg(errText(e)); }
  };
  return { msg, act, setMsg };
}

function Control({ st, reload, report }: { st: J; reload: () => void; report: (m: string) => void }) {
  const [dur, setDur] = useState<Record<string, string>>({});
  const run = async (fn: () => Promise<unknown>) => { try { await fn(); report(""); } catch (e) { report(errText(e)); } reload(); };
  return (
    <>
      <section className="card">
        <div className="card-head">
          <h2>Watering</h2>
          <div className="row">
            {st.estop
              ? <button className="primary" onClick={() => confirm("Only reset after the cause is found and it is safe to restart. Reset the emergency stop?") &&
                  run(() => api.post("/api/safety/estop/reset", { confirm: true }))}>Reset emergency stop</button>
              : <button className="estop" onClick={() => run(() => api.post("/api/safety/estop"))}>EMERGENCY STOP</button>}
          </div>
        </div>
        {st.estop && <div className="banner critical">Emergency stop is latched: all outputs are off and nothing can start.</div>}
        <p className="muted">Software stop only. A hardware emergency stop that cuts actuator power must also be installed.</p>
        <div className="row">
          <label className="check"><input type="checkbox" checked={st.auto_enabled}
            onChange={(e) => run(async () => {
              const s = await api.get<J>("/api/irrigation/setup");
              await api.put("/api/irrigation/settings", { ...s.settings, auto_enabled: e.target.checked });
            })} />Automatic irrigation (schedules and moisture triggers)</label>
          <span className={st.auto_allowed ? "badge ok" : "badge"}>{st.auto_allowed ? "active" : `not running: ${st.auto_detail}`}</span>
        </div>
      </section>
      {st.zones.length === 0 && <p className="muted">No irrigation zones configured yet (Advanced mode → Setup).</p>}
      <div className="tiles">
        {st.zones.map((z: J) => (
          <div key={z.id} className={`tile ${z.running ? "good" : ""}`} style={{ gridColumn: "span 2" }}>
            <div className="tile-label">{z.name} · {z.kind}</div>
            <div className="tile-value" style={{ fontSize: 18 }}>
              {z.running ? `${z.running.phase} (${z.running.source}) ${z.running.elapsed_s}/${z.running.planned_s}s` : "idle"}
              {z.running?.volume_l != null && <span className="unit">{z.running.volume_l} L</span>}</div>
            <div className="tile-note">{z.tank_ok ? "water source ok" : `⚠ ${z.tank_detail}`} · last run {fmtTs(z.last_end)}</div>
            <div className="row" style={{ marginTop: 8 }}>
              {z.running ? <button className="pill" onClick={() => run(() => api.post(`/api/irrigation/zones/${z.id}/stop`))}>Stop</button> : <>
                <input size={5} type="number" placeholder="sec" value={dur[z.id] ?? ""} onChange={(e) => setDur({ ...dur, [z.id]: e.target.value })} />
                <button className="primary" disabled={st.estop || !z.enabled}
                  onClick={() => run(() => api.post(`/api/irrigation/zones/${z.id}/run`, { duration_s: dur[z.id] ? Number(dur[z.id]) : null }))}>Water now</button></>}
            </div>
          </div>))}
      </div>
    </>
  );
}

function Outputs({ st, reload, report }: { st: J; reload: () => void; report: (m: string) => void }) {
  return (
    <section className="card">
      <h2>Outputs (manual control)</h2>
      <p className="muted">Interlocks and each output's maximum runtime still apply. A pump only starts while one of its valves is open.</p>
      <div className="table-wrap"><table>
        <thead><tr><th>Output</th><th>Kind</th><th>State</th><th>Max runtime</th><th /></tr></thead>
        <tbody>{Object.entries<J>(st.outputs).map(([id, o]) => (
          <tr key={id}><td><code>{id}</code> {o.name}</td><td>{o.kind}</td>
            <td><span className={`dot-s ${o.on ? "ok" : ""}`} /> {o.on ? `ON ${o.on_for_s}s` : "off"}</td><td>{o.max_runtime_s}s</td>
            <td className="row">
              <button className="pill" onClick={async () => { try { await api.post(`/api/actuators/${id}/command`, { state: "on", duration_s: 30 }); report(""); } catch (e) { report(errText(e)); } reload(); }}>On 30s</button>
              <button className="pill" onClick={async () => { await api.post(`/api/actuators/${id}/command`, { state: "off" }); reload(); }}>Off</button></td></tr>))}</tbody>
      </table></div>
    </section>
  );
}

function History() {
  const [h] = usePoll<J>("/api/irrigation/history?days=30", 15000);
  if (!h) return null;
  return (
    <section className="card">
      <h2>Irrigation history and water use</h2>
      <p className="muted">{h.note}</p>
      <div className="table-wrap"><table>
        <thead><tr><th>Date</th><th>Runs</th><th>Seconds</th><th>Measured L</th><th>Estimated L</th></tr></thead>
        <tbody>{h.daily.map((d: J) => <tr key={d.date}><td>{d.date}</td><td>{d.runs}</td><td>{d.seconds}</td><td>{d.measured_l}</td><td>{d.estimated_l}</td></tr>)}</tbody>
      </table></div>
      <h3>Recent runs</h3>
      <div className="table-wrap"><table>
        <thead><tr><th>Start</th><th>Zone</th><th>Source</th><th>Planned</th><th>Actual</th><th>Litres</th><th>Ended because</th></tr></thead>
        <tbody>{h.runs.slice(0, 30).map((r: J) => (
          <tr key={r.id}><td>{fmtTs(r.start_ts)}</td><td>{r.zone_id}</td><td>{r.source}</td><td>{r.planned_s}s</td><td>{r.actual_s ?? "…"}s</td>
            <td>{r.volume_l ?? (r.volume_estimate_l != null ? `~${r.volume_estimate_l}` : "–")}</td><td style={{ whiteSpace: "normal" }}>{r.end_reason ?? "running"}</td></tr>))}</tbody>
      </table></div>
    </section>
  );
}

function Commissioning() {
  const [s, , reload] = usePoll<J>("/api/safety", 0);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const { msg, act } = useAct();
  if (!s) return null;
  return (
    <section className="card">
      <h2>Commissioning checklist</h2>
      <p><span className={s.production_automation_allowed ? "badge ok" : "badge"}>{s.production_automation_allowed ? "automation allowed" : "automation blocked"}</span> {s.reason}</p>
      <p className="muted">Automatic irrigation only runs when every check has passed. Software tests check the interlock logic; they cannot see your wiring, so physical checks need you to do the test and attest it.
        Changing outputs, tanks or zone wiring invalidates passes. {s.note}</p>
      {s.checks.map((c: J) => (
        <div key={c.id} className="panel" style={{ marginBottom: 8 }}>
          <b>{c.passed ? "✅" : "⬜"} {c.title}</b>{c.invalidated_by_config_change && <span className="badge">invalidated by a configuration change</span>}
          <span className="muted">{c.instructions}</span>
          {c.auto && <div className="row"><button className="pill" onClick={() => act(async () => { await api.post(`/api/safety/checks/${c.id}/run`); reload(); }, "Test run.")}>Run software test</button>
            <span className="muted">{c.auto.ok ? "✓ " : "✗ "}{c.auto.detail}</span></div>}
          {c.manual && (c.manual.attested
            ? <div className="row"><span className="muted">Attested {fmtTs(c.manual.ts)}: {c.manual.note}</span>
              <button className="pill" onClick={() => act(async () => { await fetch(`/api/safety/checks/${c.id}`, { method: "DELETE" }); reload(); })}>Revoke</button></div>
            : <div className="row"><input style={{ flex: 1, minWidth: 200 }} placeholder="What did you physically test, and what happened?" value={notes[c.id] ?? ""}
                onChange={(e) => setNotes({ ...notes, [c.id]: e.target.value })} />
              <button className="pill" onClick={() => act(async () => { await api.post(`/api/safety/checks/${c.id}/attest`, { note: notes[c.id] ?? "" }); reload(); }, "Attested.")}>I performed this test</button></div>)}
        </div>))}
      <span className="muted">{msg}</span>
    </section>
  );
}

function Setup({ onChange }: { onChange: () => void }) {
  const [d, , reload] = usePoll<J>("/api/irrigation/setup", 0);
  const { msg, act } = useAct();
  const [a, setA] = useState({ id: "", name: "", kind: "valve", driver: "simulated_output", max_runtime_s: "600", addr: "{}", fb: "" });
  const [t, setT] = useState({ id: "", name: "", level: "", float: "", min: "15" });
  const blankZ = { id: "", name: "", kind: "soil", valve_id: "", pump_id: "", tank_id: "", flow: "", max_duration_s: "600", default_duration_s: "300",
    min_interval_s: "3600", min_flow: "", max_flow: "", expected: "", moist: "", start_below: "", stop_at: "", sched: [] as J[] };
  const [z, setZ] = useState<J>(blankZ);
  if (!d) return null;
  const done = () => { reload(); onChange(); };
  const n = (v: string) => (v === "" ? null : Number(v));
  const drv = d.output_drivers.find((x: J) => x.name === a.driver);
  const acts: J[] = d.actuators;

  return (
    <section className="card">
      <h2>Setup: outputs, tanks, zones</h2>
      <p className="muted">Each output needs a maximum runtime (hard limit). A zone with a pump needs a tank with a level sensor and/or float switch sensor. Add the sensors first (Hardware page).</p>
      <h3>Outputs</h3>
      <div className="table-wrap"><table><thead><tr><th>ID</th><th>Kind</th><th>Driver</th><th>Address</th><th>Max s</th><th /></tr></thead>
        <tbody>{acts.map((x) => <tr key={x.id}><td><code>{x.id}</code> {x.name}</td><td>{x.kind}</td><td>{x.driver}</td><td><code>{JSON.stringify(x.address)}</code></td><td>{x.max_runtime_s}</td>
          <td><button className="pill" onClick={() => act(async () => { const r = await fetch(`/api/actuators/${x.id}`, { method: "DELETE" }); if (!r.ok) throw new Error(await r.text()); done(); })}>Delete</button></td></tr>)}</tbody></table></div>
      <div className="form">
        <label>ID<input value={a.id} onChange={(e) => setA({ ...a, id: e.target.value })} /></label>
        <label>Name<input value={a.name} onChange={(e) => setA({ ...a, name: e.target.value })} /></label>
        <label>Kind<select value={a.kind} onChange={(e) => setA({ ...a, kind: e.target.value })}>{["valve", "pump", "dosing", "other"].map((k) => <option key={k}>{k}</option>)}</select></label>
        <label>Driver<select value={a.driver} onChange={(e) => setA({ ...a, driver: e.target.value })}>{d.output_drivers.map((x: J) => <option key={x.name} value={x.name}>{x.label}</option>)}</select></label>
        <label>Max runtime (s)<input type="number" value={a.max_runtime_s} onChange={(e) => setA({ ...a, max_runtime_s: e.target.value })} /></label>
        <label>Feedback sensor ID (optional)<input value={a.fb} onChange={(e) => setA({ ...a, fb: e.target.value })} /></label>
      </div>
      <label>Address (JSON)<textarea rows={2} value={a.addr} onChange={(e) => setA({ ...a, addr: e.target.value })} /></label>
      <p className="muted">{drv?.address_help} {drv && !drv.hardware_tested && "Not yet tested on physical hardware."}</p>
      <button className="primary" onClick={() => act(async () => {
        await api.post("/api/actuators", { id: a.id, name: a.name, kind: a.kind, driver: a.driver, address: JSON.parse(a.addr), max_runtime_s: Number(a.max_runtime_s), feedback_sensor_id: a.fb || null }); done(); }, "Output added.")}>Add output</button>

      <h3>Tanks</h3>
      <ul className="checks">{d.tanks.map((x: J) => <li key={x.id}><code>{x.id}</code> {x.name}: level <code>{x.level_sensor_id ?? "–"}</code>, float <code>{x.float_sensor_id ?? "–"}</code>, min {x.min_level_pct}%
        {" "}<button className="pill" onClick={() => act(async () => { const r = await fetch(`/api/irrigation/tanks/${x.id}`, { method: "DELETE" }); if (!r.ok) throw new Error(await r.text()); done(); })}>Delete</button></li>)}</ul>
      <div className="form">
        <label>ID<input value={t.id} onChange={(e) => setT({ ...t, id: e.target.value })} /></label>
        <label>Name<input value={t.name} onChange={(e) => setT({ ...t, name: e.target.value })} /></label>
        <label>Level sensor ID<input value={t.level} onChange={(e) => setT({ ...t, level: e.target.value })} /></label>
        <label>Float switch sensor ID (1 = water ok)<input value={t.float} onChange={(e) => setT({ ...t, float: e.target.value })} /></label>
        <label>Minimum level (%)<input type="number" value={t.min} onChange={(e) => setT({ ...t, min: e.target.value })} /></label>
      </div>
      <button className="primary" onClick={() => act(async () => { await api.post("/api/irrigation/tanks", { id: t.id, name: t.name, level_sensor_id: t.level || null, float_sensor_id: t.float || null, min_level_pct: Number(t.min) }); done(); }, "Tank added.")}>Add tank</button>

      <h3>Zones</h3>
      <ul className="checks">{d.zones.map((x: J) => <li key={x.id}><code>{x.id}</code> {x.name} ({x.kind}): valve <code>{x.valve_id}</code>, pump <code>{x.pump_id ?? "–"}</code>, tank <code>{x.tank_id ?? "–"}</code>, max {x.max_duration_s}s, {x.schedule.length} schedule(s){x.auto_enabled ? ", auto" : ""}
        {" "}<button className="pill" onClick={() => act(async () => { const r = await fetch(`/api/irrigation/zones/${x.id}`, { method: "DELETE" }); if (!r.ok) throw new Error(await r.text()); done(); })}>Delete</button>
        {" "}<button className="pill" onClick={() => act(async () => { const r = await api.put(`/api/irrigation/zones/${x.id}`, { ...x, auto_enabled: !x.auto_enabled }); void r; done(); }, "Updated.")}>{x.auto_enabled ? "Disable auto" : "Enable auto"}</button></li>)}</ul>
      <div className="form">
        {([["id", "ID"], ["name", "Name"], ["valve_id", "Valve output ID"], ["pump_id", "Pump output ID"], ["tank_id", "Tank ID"], ["flow", "Flow sensor ID"],
          ["max_duration_s", "Max duration (s)"], ["default_duration_s", "Default duration (s)"], ["min_interval_s", "Min interval between runs (s)"],
          ["expected", "Expected flow (L/min, for estimates)"], ["min_flow", "Alarm below flow (L/min)"], ["max_flow", "Alarm above flow (L/min)"],
          ["moist", "Moisture sensor IDs (comma)"], ["start_below", "Water when moisture below (%)"], ["stop_at", "Stop when moisture reaches (%)"]] as [string, string][]).map(([k, l]) => (
          <label key={k}>{l}<input value={z[k]} onChange={(e) => setZ({ ...z, [k]: e.target.value })} /></label>))}
        <label>Kind<select value={z.kind} onChange={(e) => setZ({ ...z, kind: e.target.value })}><option>soil</option><option>hydroponic</option></select></label>
      </div>
      {z.sched.map((s: J, i: number) => (
        <div key={i} className="row">
          {DAYS.map((dn, di) => <label key={dn} className="check"><input type="checkbox" checked={s.days.includes(di)} onChange={(e) =>
            setZ({ ...z, sched: z.sched.map((x: J, j: number) => j === i ? { ...x, days: e.target.checked ? [...x.days, di] : x.days.filter((q: number) => q !== di) } : x) })} />{dn}</label>)}
          <input type="time" value={s.time} onChange={(e) => setZ({ ...z, sched: z.sched.map((x: J, j: number) => j === i ? { ...x, time: e.target.value } : x) })} />
          <input size={5} type="number" value={s.duration_s} onChange={(e) => setZ({ ...z, sched: z.sched.map((x: J, j: number) => j === i ? { ...x, duration_s: Number(e.target.value) } : x) })} /> s
          <button className="pill" onClick={() => setZ({ ...z, sched: z.sched.filter((_: J, j: number) => j !== i) })}>Remove</button></div>))}
      <div className="row" style={{ marginTop: 8 }}>
        <button className="pill" onClick={() => setZ({ ...z, sched: [...z.sched, { days: [0, 1, 2, 3, 4, 5, 6], time: "06:00", duration_s: 300 }] })}>Add schedule</button>
        <button className="primary" onClick={() => act(async () => {
          await api.post("/api/irrigation/zones", { id: z.id, name: z.name, kind: z.kind, valve_id: z.valve_id, pump_id: z.pump_id || null, tank_id: z.tank_id || null,
            flow_sensor_id: z.flow || null, max_duration_s: Number(z.max_duration_s), default_duration_s: Number(z.default_duration_s), min_interval_s: Number(z.min_interval_s),
            expected_flow_lpm: n(z.expected), min_flow_lpm: n(z.min_flow), max_flow_lpm: n(z.max_flow),
            moisture_sensor_ids: z.moist ? z.moist.split(",").map((q: string) => q.trim()) : [], moisture_start_below: n(z.start_below), moisture_stop_at: n(z.stop_at), schedule: z.sched });
          setZ(blankZ); done(); }, "Zone added.")}>Add zone</button></div>
      <p className="muted">{msg} Schedules that were missed (for example during an outage) are skipped, not caught up.</p>
    </section>
  );
}

export default function IrrigationPage({ mode }: { mode: "basic" | "advanced" }) {
  const [st, err, reload] = usePoll<J>("/api/irrigation/status", 2000);
  const [msg, setMsg] = useState("");
  if (!st) return <p className="muted">{err ?? "Loading…"}</p>;
  return (
    <>
      {msg && <div className="banner warning">{msg}</div>}
      <Control st={st} reload={reload} report={setMsg} />
      {mode === "advanced" && <Outputs st={st} reload={reload} report={setMsg} />}
      <History />
      {mode === "advanced" && <Commissioning />}
      {mode === "advanced" && <Setup onChange={reload} />}
    </>
  );
}
