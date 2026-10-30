import { useState } from "react";
import { api, usePoll } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
const errText = (e: unknown) => String(e).replace(/^Error: \d+ /, "").replace(/^\{"detail":"?|"?\}$/g, "");

function useAct() {
  const [msg, setMsg] = useState("");
  const act = async (fn: () => Promise<unknown>, ok = "Done.") => { try { await fn(); setMsg(ok); } catch (e) { setMsg(errText(e)); } };
  return { msg, act };
}
const del = async (url: string) => { const r = await fetch(url, { method: "DELETE" }); if (!r.ok) throw new Error(await r.text()); };
const num = (v: string) => (v === "" ? null : Number(v));

function Control({ st, reload }: { st: J; reload: () => void }) {
  const { msg, act } = useAct();
  const [pos, setPos] = useState<Record<string, string>>({});
  return (
    <>
      <section className="card">
        <h2>Climate control</h2>
        {st.estop && <div className="banner critical">Emergency stop is latched: all outputs are off.</div>}
        <div className="row">
          <label className="check"><input type="checkbox" checked={st.auto_enabled} onChange={(e) => act(async () => {
            await api.put("/api/climate/settings", { auto_enabled: e.target.checked, sensor_max_age_s: 30 }); reload(); })} />
            Automatic climate control (rules, windows, lighting programs)</label>
          <span className={st.auto_allowed ? "badge ok" : "badge"}>{st.auto_allowed ? "active" : `not running: ${st.auto_detail}`}</span>
        </div>
        <p className="muted">Rules never run while the commissioning checklist is incomplete. A manual override beats rules but never beats interlocks.</p>
        <span className="muted">{msg}</span>
      </section>

      <section className="card">
        <h2>Outputs</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>Output</th><th>Kind</th><th>State</th><th>Override</th><th /></tr></thead>
          <tbody>{Object.entries<J>(st.outputs).filter(([, o]) => o.kind !== "motor").map(([id, o]) => (
            <tr key={id}><td><code>{id}</code> {o.name}</td><td>{o.kind}</td>
              <td><span className={`dot-s ${o.on ? "ok" : ""}`} /> {o.on ? `ON ${o.on_for_s}s` : "off"}{o.refused && <span className="muted"> · refused: {o.refused}</span>}</td>
              <td>{o.override ?? "–"}</td>
              <td className="row">
                <button className="pill" onClick={() => act(async () => { await api.post(`/api/actuators/${id}/command`, { state: "on", duration_s: 300 }); reload(); })}>On 5 min</button>
                <button className="pill" onClick={() => act(async () => { await api.post(`/api/actuators/${id}/command`, { state: "off", duration_s: 300 }); reload(); })}>Off 5 min</button>
                <button className="pill" onClick={() => act(async () => { await api.post(`/api/climate/outputs/${id}/release`); reload(); })}>Auto</button></td></tr>))}</tbody>
        </table></div>
      </section>

      <section className="card">
        <h2>Windows and screens</h2>
        <p className="muted">Position is an estimate from motor run time (limit switches correct it). Rain/wind interlocks close vents.</p>
        {st.windows.length === 0 && <p className="muted">None configured.</p>}
        {st.windows.map((w: J) => (
          <div key={w.id} className="panel" style={{ marginBottom: 8 }}>
            <b>{w.name}</b> ({w.kind}) — {w.position_pct === null ? "position unknown (will home on first move)" : `${w.position_pct}% open (estimate)`}
            {w.moving && <span className="badge ok">{w.moving}ing</span>}{w.hazard && <span className="badge">closing: {w.hazard}</span>}
            <div className="row">
              <input size={4} type="number" placeholder="%" value={pos[w.id] ?? ""} onChange={(e) => setPos({ ...pos, [w.id]: e.target.value })} />
              <button className="pill" onClick={() => act(async () => { await api.post(`/api/climate/windows/${w.id}/position`, { position_pct: Number(pos[w.id] ?? 0) }); reload(); })}>Move (30 min)</button>
              {[0, 50, 100].map((p) => <button key={p} className="pill" onClick={() => act(async () => { await api.post(`/api/climate/windows/${w.id}/position`, { position_pct: p }); reload(); })}>{p}%</button>)}
              <button className="pill" onClick={() => act(async () => { await api.post(`/api/climate/windows/${w.id}/release`); reload(); })}>Auto</button>
            </div>
          </div>))}
      </section>

      <section className="card">
        <h2>Lighting today</h2>
        <p>DLI so far <b>{st.lighting.dli_mol}</b> mol/m² · lights on <b>{st.lighting.light_on_h}</b> h · energy <b>{st.lighting.light_kwh}</b> kWh</p>
        <p className="muted">{st.lighting.note}</p>
        <ul className="checks">{st.lighting.programs.map((p: J) => <li key={p.id}>{p.on ? "💡" : "○"} {p.name} ({p.mode})</li>)}</ul>
      </section>

      <section className="card">
        <h2>Rules</h2>
        {st.rules.length === 0 && <p className="muted">No rules yet (Advanced mode → Rule builder).</p>}
        <ul className="checks">{st.rules.map((r: J) => (
          <li key={r.id}>{r.active ? "🟢" : "⚪"} <b>{r.name}</b> <span className="muted">priority {r.priority}{r.generated ? " · generated" : ""}{r.enabled ? "" : " · disabled"}</span></li>))}</ul>
      </section>
    </>
  );
}

const blankCond = (t: string): J => ({
  sensor: { type: "sensor", sensors: [""], agg: "mean", op: ">", on: 28, off: 26 },
  vpd: { type: "vpd", temp_sensors: [""], rh_sensors: [""], op: "<", on: 0.4, off: 0.6 },
  time: { type: "time", start: "07:00", end: "19:00" },
  month: { type: "month", months: [5, 6, 7, 8] },
  output: { type: "output", output_id: "", state: "on" },
}[t] as J);

function RuleBuilder({ d, reload }: { d: J; reload: () => void }) {
  const { msg, act } = useAct();
  const blank = { id: "", name: "", priority: 50, match: "all", conditions: [blankCond("sensor")] as J[], actions: [{ output_id: "", state: "on" }] as J[],
    on_delay_s: 0, off_delay_s: 0, min_on_s: 0, min_off_s: 0, max_on_s: "", cooldown_s: 0, notify: false, on_fault: "off" };
  const [r, setR] = useState<J>(blank);
  const setC = (i: number, patch: J) => setR({ ...r, conditions: r.conditions.map((c: J, j: number) => (j === i ? { ...c, ...patch } : c)) });
  const setA = (i: number, patch: J) => setR({ ...r, actions: r.actions.map((a: J, j: number) => (j === i ? { ...a, ...patch } : a)) });
  const ids = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
  const outs = d.outputs.filter((o: J) => o.kind !== "motor");

  return (
    <section className="card">
      <h2>Rule builder</h2>
      <div className="form">
        <label>ID<input value={r.id} onChange={(e) => setR({ ...r, id: e.target.value })} /></label>
        <label>Name<input value={r.name} onChange={(e) => setR({ ...r, name: e.target.value })} /></label>
        <label>Priority (0-99, higher wins)<input type="number" value={r.priority} onChange={(e) => setR({ ...r, priority: Number(e.target.value) })} /></label>
        <label>Conditions must match<select value={r.match} onChange={(e) => setR({ ...r, match: e.target.value })}><option value="all">all (AND)</option><option value="any">any (OR)</option></select></label>
      </div>
      <h3>IF</h3>
      {r.conditions.map((c: J, i: number) => (
        <div key={i} className="panel" style={{ marginBottom: 8 }}>
          <div className="row">
            <select value={c.type} onChange={(e) => setR({ ...r, conditions: r.conditions.map((x: J, j: number) => (j === i ? blankCond(e.target.value) : x)) })}>
              <option value="sensor">Sensor value</option><option value="vpd">VPD</option><option value="time">Time of day</option><option value="month">Months</option><option value="output">Output state</option></select>
            {c.type === "sensor" && <>
              <input placeholder="sensor IDs, comma" value={c.sensors.join(",")} onChange={(e) => setC(i, { sensors: ids(e.target.value) })} />
              <select value={c.agg} onChange={(e) => setC(i, { agg: e.target.value })}><option>mean</option><option>min</option><option>max</option></select></>}
            {c.type === "vpd" && <>
              <input placeholder="temperature sensor IDs" value={c.temp_sensors.join(",")} onChange={(e) => setC(i, { temp_sensors: ids(e.target.value) })} />
              <input placeholder="humidity sensor IDs" value={c.rh_sensors.join(",")} onChange={(e) => setC(i, { rh_sensors: ids(e.target.value) })} /></>}
            {(c.type === "sensor" || c.type === "vpd") && <>
              <select value={c.op} onChange={(e) => setC(i, { op: e.target.value })}><option value=">">&gt;</option><option value="<">&lt;</option></select>
              <label className="inline">turns on at<input size={5} type="number" value={c.on} onChange={(e) => setC(i, { on: Number(e.target.value) })} /></label>
              <label className="inline">stops at<input size={5} type="number" value={c.off} onChange={(e) => setC(i, { off: Number(e.target.value) })} /></label></>}
            {c.type === "time" && <><input type="time" value={c.start} onChange={(e) => setC(i, { start: e.target.value })} /> to <input type="time" value={c.end} onChange={(e) => setC(i, { end: e.target.value })} /></>}
            {c.type === "month" && <input placeholder="months 1-12, comma" value={c.months.join(",")} onChange={(e) => setC(i, { months: ids(e.target.value).map(Number) })} />}
            {c.type === "output" && <><input placeholder="output ID" value={c.output_id} onChange={(e) => setC(i, { output_id: e.target.value })} />
              <select value={c.state} onChange={(e) => setC(i, { state: e.target.value })}><option>on</option><option>off</option></select></>}
            <button className="pill" onClick={() => setR({ ...r, conditions: r.conditions.filter((_: J, j: number) => j !== i) })}>Remove</button>
          </div>
        </div>))}
      <button className="pill" onClick={() => setR({ ...r, conditions: [...r.conditions, blankCond("sensor")] })}>Add condition</button>
      <p className="muted">“Turns on at / stops at” is the hysteresis band: the condition stays true until the value passes the stop value. Unknown or stale sensors never switch anything on.</p>

      <h3>THEN</h3>
      {r.actions.map((a: J, i: number) => (
        <div key={i} className="row" style={{ marginBottom: 6 }}>
          <select value={"window_id" in a ? "window" : "output"} onChange={(e) => setR({ ...r, actions: r.actions.map((x: J, j: number) => (j === i ? (e.target.value === "window" ? { window_id: "", position_pct: 100 } : { output_id: "", state: "on" }) : x)) })}>
            <option value="output">Switch output</option><option value="window">Move window</option></select>
          {"window_id" in a
            ? <><select value={a.window_id} onChange={(e) => setA(i, { window_id: e.target.value })}><option value="">window…</option>{d.windows.map((w: J) => <option key={w.id} value={w.id}>{w.name}</option>)}</select>
              <input size={4} type="number" value={a.position_pct} onChange={(e) => setA(i, { position_pct: Number(e.target.value) })} /> % open</>
            : <><select value={a.output_id} onChange={(e) => setA(i, { output_id: e.target.value })}><option value="">output…</option>{outs.map((o: J) => <option key={o.id} value={o.id}>{o.name} ({o.kind})</option>)}</select>
              <select value={a.state} onChange={(e) => setA(i, { state: e.target.value })}><option>on</option><option>off</option></select></>}
          <button className="pill" onClick={() => setR({ ...r, actions: r.actions.filter((_: J, j: number) => j !== i) })}>Remove</button>
        </div>))}
      <button className="pill" onClick={() => setR({ ...r, actions: [...r.actions, { output_id: "", state: "on" }] })}>Add action</button>

      <h3>Timing and limits</h3>
      <div className="form">
        {([["on_delay_s", "Start delay (s)"], ["off_delay_s", "Stop delay (s)"], ["min_on_s", "Minimum on time (s)"], ["min_off_s", "Minimum off time (s)"],
          ["max_on_s", "Maximum on time (s, optional)"], ["cooldown_s", "Cool-down after maximum (s)"]] as [string, string][]).map(([k, l]) => (
          <label key={k}>{l}<input type="number" value={r[k]} onChange={(e) => setR({ ...r, [k]: e.target.value })} /></label>))}
        <label className="check"><input type="checkbox" checked={r.notify} onChange={(e) => setR({ ...r, notify: e.target.checked })} />Notify when it activates</label>
        <label>If a sensor fails<select value={r.on_fault} onChange={(e) => setR({ ...r, on_fault: e.target.value })}><option value="off">switch off</option><option value="hold">hold current state</option></select></label>
      </div>
      <button className="primary" onClick={() => act(async () => {
        await api.post("/api/climate/rules", { ...r, max_on_s: num(String(r.max_on_s)), on_delay_s: Number(r.on_delay_s), off_delay_s: Number(r.off_delay_s),
          min_on_s: Number(r.min_on_s), min_off_s: Number(r.min_off_s), cooldown_s: Number(r.cooldown_s) });
        setR(blank); reload(); }, "Rule saved.")}>Save rule</button> <span className="muted">{msg}</span>
      <h3>Existing rules</h3>
      <ul className="checks">{d.rules.map((x: J) => (
        <li key={x.id}><b>{x.name}</b> <code>{x.id}</code> prio {x.priority}{x.generated ? " (generated)" : ""} — {x.conditions.length} condition(s), {x.actions.length} action(s)
          {" "}<button className="pill" onClick={() => act(async () => { await api.put(`/api/climate/rules/${x.id}`, { ...x, enabled: !x.enabled }); reload(); })}>{x.enabled ? "Disable" : "Enable"}</button>
          {" "}<button className="pill" onClick={() => act(async () => { await del(`/api/climate/rules/${x.id}`); reload(); })}>Delete</button></li>))}</ul>
    </section>
  );
}

function Template({ d, reload }: { d: J; reload: () => void }) {
  const { msg, act } = useAct();
  const [t, setT] = useState<J>({ temp_sensors: "", day_start: "07:00", night_start: "19:00", heater_id: "", circulation_fan_id: "", day_heat_on_below: "", day_heat_off_above: "",
    night_heat_on_below: "", night_heat_off_above: "", vent_window_ids: "", vent_open_above: "", vent_close_below: "", exhaust_fan_ids: "", fan_on_above: "", fan_off_below: "" });
  const list = (s: string) => s.split(",").map((x: string) => x.trim()).filter(Boolean);
  const F = ([["temp_sensors", "Temperature sensor IDs"], ["day_start", "Day starts (HH:MM)"], ["night_start", "Night starts (HH:MM)"], ["heater_id", "Heater output ID"], ["circulation_fan_id", "Circulation fan ID (needed by heater)"],
    ["day_heat_on_below", "Day: heat when below °C"], ["day_heat_off_above", "Day: stop heating above °C"], ["night_heat_on_below", "Night: heat when below °C"], ["night_heat_off_above", "Night: stop heating above °C"],
    ["vent_window_ids", "Vent window IDs"], ["vent_open_above", "Open vents above °C"], ["vent_close_below", "Close vents below °C"], ["exhaust_fan_ids", "Exhaust fan IDs"], ["fan_on_above", "Fans on above °C"], ["fan_off_below", "Fans off below °C"]] as [string, string][]);
  return (
    <section className="card">
      <h2>Temperature setpoints → rules</h2>
      <p className="muted">Enter YOUR targets; nothing is assumed. This replaces previously generated rules with day/night heating, ventilation and fan rules. Crop profiles on the Plants page can suggest starting values. Available outputs: {d.outputs.map((o: J) => o.id).join(", ") || "none"}.</p>
      <div className="form">{F.map(([k, l]) => <label key={k}>{l}<input value={t[k]} onChange={(e) => setT({ ...t, [k]: e.target.value })} /></label>)}</div>
      <button className="primary" onClick={() => act(async () => {
        const body: J = { temp_sensors: list(t.temp_sensors), day_start: t.day_start, night_start: t.night_start, heater_id: t.heater_id || null, circulation_fan_id: t.circulation_fan_id || null,
          vent_window_ids: list(t.vent_window_ids), exhaust_fan_ids: list(t.exhaust_fan_ids) };
        for (const k of ["day_heat_on_below", "day_heat_off_above", "night_heat_on_below", "night_heat_off_above", "vent_open_above", "vent_close_below", "fan_on_above", "fan_off_below"]) body[k] = num(t[k]);
        const r = await api.post<J>("/api/climate/templates/setpoints", body); reload(); return r; }, "Rules generated.")}>Generate rules</button> <span className="muted">{msg}</span>
    </section>
  );
}

function Setup({ d, reload }: { d: J; reload: () => void }) {
  const { msg, act } = useAct();
  const [o, setO] = useState({ id: "", name: "", kind: "fan", driver: "simulated_output", max_runtime_s: "3600", addr: "{}", il: "{}" });
  const [w, setW] = useState<J>({ id: "", name: "", kind: "vent", open_output_id: "", close_output_id: "", travel_time_s: "", open_limit_sensor_id: "", closed_limit_sensor_id: "", rain_sensor_id: "", wind_sensor_id: "", wind_max_ms: "" });
  const [l, setL] = useState<J>({ id: "", name: "", output_ids: "", mode: "photoperiod", start_time: "06:00", photoperiod_h: "16", ppfd_sensor_id: "", dli_target: "", on_below_ppfd: "", off_above_ppfd: "", power_sensor_id: "" });
  const drv = d.output_drivers.find((x: J) => x.name === o.driver);
  return (
    <section className="card">
      <h2>Setup: outputs, windows, lighting</h2>
      <h3>Climate outputs</h3>
      <div className="table-wrap"><table><thead><tr><th>ID</th><th>Kind</th><th>Driver</th><th>Max s</th><th>Interlocks</th><th /></tr></thead>
        <tbody>{d.outputs.map((x: J) => <tr key={x.id}><td><code>{x.id}</code> {x.name}</td><td>{x.kind}</td><td>{x.driver}</td><td>{x.max_runtime_s}</td>
          <td><code>{JSON.stringify(x.interlocks)}</code></td><td><button className="pill" onClick={() => act(async () => { await del(`/api/actuators/${x.id}`); reload(); })}>Delete</button></td></tr>)}</tbody></table></div>
      <div className="form">
        <label>ID<input value={o.id} onChange={(e) => setO({ ...o, id: e.target.value })} /></label>
        <label>Name<input value={o.name} onChange={(e) => setO({ ...o, name: e.target.value })} /></label>
        <label>Kind<select value={o.kind} onChange={(e) => setO({ ...o, kind: e.target.value })}>{d.kinds.map((k: string) => <option key={k}>{k}</option>)}</select></label>
        <label>Driver<select value={o.driver} onChange={(e) => setO({ ...o, driver: e.target.value })}>{d.output_drivers.map((x: J) => <option key={x.name} value={x.name}>{x.label}</option>)}</select></label>
        <label>Max runtime (s, hard limit)<input type="number" value={o.max_runtime_s} onChange={(e) => setO({ ...o, max_runtime_s: e.target.value })} /></label>
      </div>
      <label>Address (JSON)<textarea rows={2} value={o.addr} onChange={(e) => setO({ ...o, addr: e.target.value })} /></label>
      <label>Interlocks (JSON): requires_on, forbids_on, min_on_s, min_off_s, stop_if {"{sensor_id, above}"}, windows_max_open_pct<textarea rows={2} value={o.il} onChange={(e) => setO({ ...o, il: e.target.value })} /></label>
      <p className="muted">{drv?.address_help} Heaters and CO₂ outputs REQUIRE a stop_if safety limit and independent hardware protection. Motor outputs are for windows only.</p>
      <button className="primary" onClick={() => act(async () => { await api.post("/api/actuators", { id: o.id, name: o.name, kind: o.kind, driver: o.driver, max_runtime_s: Number(o.max_runtime_s), address: JSON.parse(o.addr), interlocks: JSON.parse(o.il) }); reload(); }, "Output added.")}>Add output</button>

      <h3>Windows / screens (two motor outputs: open and close)</h3>
      <ul className="checks">{d.windows.map((x: J) => <li key={x.id}><code>{x.id}</code> {x.name} ({x.kind}) travel {x.travel_time_s}s{" "}<button className="pill" onClick={() => act(async () => { await del(`/api/climate/windows/${x.id}`); reload(); })}>Delete</button></li>)}</ul>
      <div className="form">{([["id", "ID"], ["name", "Name"], ["open_output_id", "Open output ID"], ["close_output_id", "Close output ID"], ["travel_time_s", "Full travel time (s)"], ["open_limit_sensor_id", "Open limit sensor ID"],
        ["closed_limit_sensor_id", "Closed limit sensor ID"], ["rain_sensor_id", "Rain sensor ID (1 = rain)"], ["wind_sensor_id", "Wind sensor ID"], ["wind_max_ms", "Close above wind (m/s)"]] as [string, string][]).map(([k, lab]) =>
        <label key={k}>{lab}<input value={w[k]} onChange={(e) => setW({ ...w, [k]: e.target.value })} /></label>)}
        <label>Kind<select value={w.kind} onChange={(e) => setW({ ...w, kind: e.target.value })}><option>vent</option><option>shade</option></select></label></div>
      <button className="primary" onClick={() => act(async () => { await api.post("/api/climate/windows", { ...w, travel_time_s: Number(w.travel_time_s), wind_max_ms: num(w.wind_max_ms),
        open_limit_sensor_id: w.open_limit_sensor_id || null, closed_limit_sensor_id: w.closed_limit_sensor_id || null, rain_sensor_id: w.rain_sensor_id || null, wind_sensor_id: w.wind_sensor_id || null }); reload(); }, "Window added.")}>Add window</button>
      <p className="muted">The motors' maximum runtime must be at least 1.2 × the travel time. Fit end-of-travel limit switches or motor protection in hardware.</p>

      <h3>Lighting programs</h3>
      <ul className="checks">{d.lights.map((x: J) => <li key={x.id}><code>{x.id}</code> {x.name}: {x.mode}, from {x.start_time} for {x.photoperiod_h} h{" "}<button className="pill" onClick={() => act(async () => { await del(`/api/climate/lights/${x.id}`); reload(); })}>Delete</button></li>)}</ul>
      <div className="form">{([["id", "ID"], ["name", "Name"], ["output_ids", "Light output IDs (comma)"], ["start_time", "Photoperiod starts (HH:MM)"], ["photoperiod_h", "Photoperiod (h)"], ["ppfd_sensor_id", "PAR sensor ID"],
        ["dli_target", "Target DLI (mol/m²/day)"], ["on_below_ppfd", "DLI mode: lights on below PPFD"], ["off_above_ppfd", "DLI mode: off above PPFD"], ["power_sensor_id", "Power sensor ID (W, optional)"]] as [string, string][]).map(([k, lab]) =>
        <label key={k}>{lab}<input value={l[k]} onChange={(e) => setL({ ...l, [k]: e.target.value })} /></label>)}
        <label>Mode<select value={l.mode} onChange={(e) => setL({ ...l, mode: e.target.value })}><option value="photoperiod">Fixed photoperiod</option><option value="dli">Top up to target DLI</option></select></label></div>
      <button className="primary" onClick={() => act(async () => { await api.post("/api/climate/lights", { id: l.id, name: l.name, mode: l.mode, start_time: l.start_time, photoperiod_h: Number(l.photoperiod_h),
        output_ids: l.output_ids.split(",").map((x: string) => x.trim()).filter(Boolean), ppfd_sensor_id: l.ppfd_sensor_id || null, power_sensor_id: l.power_sensor_id || null,
        dli_target: num(l.dli_target), on_below_ppfd: num(l.on_below_ppfd), off_above_ppfd: num(l.off_above_ppfd) }); reload(); }, "Lighting program added.")}>Add lighting program</button>
      <p className="muted">PPFD (photons) is not lux. The light output's maximum runtime must cover the whole photoperiod. {msg}</p>
    </section>
  );
}

export default function ClimatePage({ mode }: { mode: "basic" | "advanced" }) {
  const [st, err, reloadSt] = usePoll<J>("/api/climate/status", 2000);
  const [d, , reloadD] = usePoll<J>("/api/climate/setup", 0);
  if (!st || !d) return <p className="muted">{err ?? "Loading…"}</p>;
  const reload = () => { reloadSt(); reloadD(); };
  return (
    <>
      <Control st={st} reload={reload} />
      {mode === "advanced" && <><RuleBuilder d={d} reload={reload} /><Template d={d} reload={reload} /><Setup d={d} reload={reload} /></>}
    </>
  );
}
