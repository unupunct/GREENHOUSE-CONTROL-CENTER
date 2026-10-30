import { useEffect, useState } from "react";
import { api } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
interface Meta { label: string; section: string; unit: string; assumption: boolean; help: string }
const SKIP = new Set(["tier", "loads"]);

function Result({ title, r, children }: { title: string; r: J; children?: React.ReactNode }) {
  const final = r?.status === "final";
  return (
    <div className="panel">
      <b>{title}</b>{" "}
      <span className={final ? "badge ok" : "badge"}>{final ? "calculated from your inputs" : "needs input"}</span>
      {children}
      {r?.missing?.length > 0 && <p className="muted">Missing: {r.missing.join(", ")}</p>}
    </div>
  );
}

const kv = (o: J, keys: [string, string, string?][]) => (
  <ul className="checks">{keys.filter(([k]) => o[k] !== undefined && o[k] !== null).map(([k, l, u]) =>
    <li key={k}>{l}: <b>{typeof o[k] === "number" ? o[k].toLocaleString() : String(o[k])}</b> {u}</li>)}</ul>
);

export default function PlannerPage() {
  const [opts, setOpts] = useState<J | null>(null);
  const [meta, setMeta] = useState<Record<string, Meta>>({});
  const [plan, setPlan] = useState<J | null>(null);
  const [msg, setMsg] = useState("");
  const [cable, setCable] = useState({ length_m: 20, current_a: 5, voltage_v: 24, max_drop_pct: 3 });
  const [cableOut, setCableOut] = useState<J | null>(null);

  useEffect(() => {
    api.get<{ options: J; fields: Record<string, Meta> }>("/api/planner/options").then((r) => { setOpts(r.options); setMeta(r.fields); });
  }, []);
  useEffect(() => {
    if (!opts) return;
    const t = setTimeout(() => api.post<J>("/api/planner/plan", opts).then(setPlan).catch(() => {}), 300);
    return () => clearTimeout(t);
  }, [opts]);

  if (!opts || !plan) return <p className="muted">Loading…</p>;
  const sections = [...new Set(Object.values(meta).map((m) => m.section))];
  const setField = (k: string, v: string, isNum: boolean) =>
    setOpts({ ...opts, [k]: v === "" ? null : isNum ? Number(v) : v });
  const loads: J[] = opts.loads;

  return (
    <>
      <section className="card">
        <h2>Raspberry Pi controller</h2>
        <p><b>{plan.controller.recommended}</b></p>
        <ul className="checks">{plan.controller.reasoning.map((t: string) => <li key={t}>• {t}</li>)}</ul>
        <p className="muted">{plan.controller.basis} {plan.controller.power_note}</p>
        <p className="muted">Alternatives: {plan.controller.alternatives.map((a: J) => `${a.name} (${a.when})`).join("; ")}</p>
      </section>

      <section className="card">
        <h2>Results for {plan.greenhouse.length_m} × {plan.greenhouse.width_m} m ({plan.greenhouse.area_m2} m²)</h2>
        <p className="muted">Calculated from the greenhouse page and your inputs below. Heuristics are marked as estimates;
          nothing is calculated from values you haven't supplied.</p>
        <Result title="Climate sensors" r={{ status: "final", missing: [] }}>
          <p>{plan.climate_stations.count} climate stations <span className="badge">estimate</span> — {plan.climate_stations.basis}.</p>
          <p className="muted">{plan.climate_stations.positions}</p>
        </Result>
        <Result title="Irrigation" r={plan.irrigation}>
          {kv(plan.irrigation, [["soil_zones", "Soil zones"], ["hydro_zones", "Hydroponic zones"], ["drippers", "Drippers"],
            ["all_drippers_flow_l_h", "Total dripper flow", "L/h"], ["flow_per_soil_zone_l_h", "Flow per soil zone", "L/h"],
            ["zones_simultaneously_supported", "Zones the pump can run at once"], ["volume_per_cycle_l", "Water per cycle", "L"],
            ["daily_water_l_from_demand", "Daily water from your demand figure", "L"], ["reservoir_min_l", "Minimum reservoir", "L"],
            ["pump_note", "Note"]])}
          <p className="muted">{plan.irrigation.label}</p>
        </Result>
        <Result title="Ventilation" r={plan.ventilation}>
          {kv(plan.ventilation, [["volume_m3", "Air volume", "m³"], ["geometry", "Volume basis"], ["required_airflow_m3_h", "Required airflow", "m³/h"],
            ["usable_flow_per_fan_m3_h", "Usable flow per fan", "m³/h"], ["fans", "Exhaust fans"], ["note", "Note"]])}
          <p className="muted">{plan.ventilation.note_geometry}</p>
        </Result>
        <Result title="Lighting" r={plan.lighting}>
          {kv(plan.lighting, [["target_ppfd_umol_m2_s", "Target PPFD", "µmol/m²/s"], ["supplemental_dli", "Supplemental DLI", "mol/m²/day"],
            ["supplemental_ppfd_umol_m2_s", "Supplemental PPFD", "µmol/m²/s"], ["required_fixture_ppf_umol_s", "Required fixture PPF", "µmol/s"],
            ["fixtures", "Fixtures"], ["fixtures_power_w", "Fixture power", "W"], ["energy_kwh_day", "Energy", "kWh/day"]])}
          <p className="muted">{plan.lighting.note}</p>
        </Result>
        <Result title="24 V supply and protection (conceptual)" r={plan.electrical}>
          {kv(plan.electrical, [["psu_24v_min_w", "Minimum 24 V supply", "W"], ["mains_note", "Mains"]])}
          {plan.electrical.dc_fuse_suggestions?.map((f: J) => <p key={f.load} className="muted">{f.load}: {f.current_a} A → fuse ≥ {f.suggested_fuse_a} A</p>)}
          <p className="muted">{plan.electrical.safety}</p>
        </Result>
      </section>

      <section className="card">
        <h2>Your inputs</h2>
        <p className="muted">Fields marked <span className="badge">assumption</span> have a starting value you should review. Empty fields are never filled in for you.</p>
        {sections.map((sec) => (
          <div key={sec}>
            <h3>{sec}</h3>
            <div className="form">
              {Object.entries(meta).filter(([k, m]) => m.section === sec && !SKIP.has(k)).map(([k, m]) => (
                <label key={k}>{m.label} {m.unit && <span>({m.unit})</span>} {m.assumption && <span className="badge">assumption</span>}
                  <input type="number" step="any" value={opts[k] ?? ""} onChange={(e) => setField(k, e.target.value, true)} />
                  {m.help && <span className="hint">{m.help}</span>}</label>
              ))}
            </div>
          </div>
        ))}
        <h3>Electrical loads</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>Name</th><th>Power W</th><th>Voltage</th><th>Qty</th><th /></tr></thead>
          <tbody>{loads.map((l, i) => (
            <tr key={i}>
              <td><input value={l.name} onChange={(e) => setOpts({ ...opts, loads: loads.map((x, j) => j === i ? { ...x, name: e.target.value } : x) })} /></td>
              <td><input size={6} type="number" value={l.power_w} onChange={(e) => setOpts({ ...opts, loads: loads.map((x, j) => j === i ? { ...x, power_w: Number(e.target.value) } : x) })} /></td>
              <td><select value={l.voltage} onChange={(e) => setOpts({ ...opts, loads: loads.map((x, j) => j === i ? { ...x, voltage: e.target.value } : x) })}>
                {["24VDC", "12VDC", "5VDC", "230VAC"].map((v) => <option key={v}>{v}</option>)}</select></td>
              <td><input size={3} type="number" value={l.qty} onChange={(e) => setOpts({ ...opts, loads: loads.map((x, j) => j === i ? { ...x, qty: Number(e.target.value) } : x) })} /></td>
              <td><button className="pill" onClick={() => setOpts({ ...opts, loads: loads.filter((_, j) => j !== i) })}>Remove</button></td>
            </tr>))}</tbody>
        </table></div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="pill" onClick={() => setOpts({ ...opts, loads: [...loads, { name: "New load", power_w: 10, voltage: "24VDC", qty: 1 }] })}>Add load</button>
          <button className="primary" onClick={async () => { try { await api.put("/api/planner/options", opts); setMsg("Saved."); } catch (e) { setMsg(String(e)); } }}>Save inputs</button>
          <span className="muted">{msg}</span>
        </div>
      </section>

      <section className="card">
        <h2>Cable voltage-drop calculator (DC)</h2>
        <div className="form">
          {(Object.keys(cable) as (keyof typeof cable)[]).map((k) => (
            <label key={k}>{k.replace(/_/g, " ")}<input type="number" step="any" value={cable[k]} onChange={(e) => setCable({ ...cable, [k]: Number(e.target.value) })} /></label>))}
        </div>
        <button className="pill" onClick={() => api.post<J>("/api/planner/cable", cable).then(setCableOut)}>Calculate</button>
        {cableOut && <p>Minimum {cableOut.min_cross_section_mm2} mm² → use <b>{cableOut.suggested_mm2 ?? "larger than 25"} mm²</b>; drop {cableOut.voltage_drop_v} V ({cableOut.voltage_drop_pct} %).
          <br /><span className="muted">{cableOut.note}</span></p>}
      </section>
    </>
  );
}
