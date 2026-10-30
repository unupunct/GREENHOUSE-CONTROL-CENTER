import { useEffect, useState } from "react";
import { api, usePoll, type Config, type EngInput } from "../api";

const METHODS = ["soil", "hydroponic"];
const num = (v: string) => (v === "" ? null : Number(v));

export default function ConfigPage({ mode }: { mode: "basic" | "advanced" }) {
  const [loaded] = usePoll<Config>("/api/config", 0);
  const [inputs, , reloadInputs] = usePoll<{ missing: number; items: EngInput[] }>("/api/config/engineering-inputs", 0);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => { if (loaded) setCfg(loaded); }, [loaded]);
  if (!cfg) return <p className="muted">Loading…</p>;

  const set = <K extends keyof Config>(k: K, v: Config[K]) => setCfg({ ...cfg, [k]: v });
  const save = async () => {
    try {
      setCfg(await api.put<Config>("/api/config", cfg));
      setMsg("Saved."); reloadInputs();
    } catch (e) { setMsg(`Not saved: ${e}`); }
  };

  return (
    <>
      <section className="card">
        <h2>Greenhouse</h2>
        <div className="form">
          <label>Name<input value={cfg.name} onChange={(e) => set("name", e.target.value)} /></label>
          <label>Length (m)<input type="number" min="1" step="0.5" value={cfg.length_m}
            onChange={(e) => set("length_m", Number(e.target.value))} /></label>
          <label>Width (m)<input type="number" min="1" step="0.5" value={cfg.width_m}
            onChange={(e) => set("width_m", Number(e.target.value))} /></label>
          <div className="stat">Floor area<b>{(cfg.length_m * cfg.width_m).toFixed(0)} m²</b></div>
          <fieldset><legend>Growing methods</legend>
            {METHODS.map((m) => (
              <label key={m} className="check">
                <input type="checkbox" checked={cfg.growing_methods.includes(m)}
                  onChange={(e) => set("growing_methods", e.target.checked
                    ? [...cfg.growing_methods, m] : cfg.growing_methods.filter((x) => x !== m))} />
                {m === "soil" ? "Soil" : "Hydroponics"}
              </label>
            ))}
          </fieldset>
          <label>Automation level
            <select value={cfg.automation_level} onChange={(e) => set("automation_level", e.target.value)}>
              <option value="monitor_only">Monitor only</option>
              <option value="assisted">Assisted</option>
              <option value="full">Full</option>
            </select>
          </label>
          <label>Documentation language
            <select value={cfg.language} onChange={(e) => set("language", e.target.value as "en" | "ro")}>
              <option value="en">English</option><option value="ro">Română</option>
            </select>
          </label>
        </div>
        <button className="primary" onClick={save}>Save</button> <span className="muted">{msg}</span>
      </section>

      <section className="card">
        <h2>Details needed for engineering calculations
          {inputs && inputs.missing > 0 && <span className="badge">{inputs.missing} missing</span>}</h2>
        <p className="muted">These are never assumed. Fan sizing, heating, irrigation and electrical
          design stay "not final" until they are provided.</p>
        <div className="form">
          <label>Gutter height (m)<input type="number" step="0.1" value={cfg.height_m ?? ""}
            onChange={(e) => set("height_m", num(e.target.value))} /></label>
          <label>Ridge height (m)<input type="number" step="0.1" value={cfg.ridge_height_m ?? ""}
            onChange={(e) => set("ridge_height_m", num(e.target.value))} /></label>
          <label>Orientation
            <select value={cfg.orientation ?? ""} onChange={(e) => set("orientation", e.target.value || null)}>
              <option value="">Not set</option>
              <option value="north_south">Long axis north–south</option>
              <option value="east_west">Long axis east–west</option>
            </select>
          </label>
          <label>Covering<input value={cfg.construction ?? ""} placeholder="glass / polycarbonate / film"
            onChange={(e) => set("construction", e.target.value || null)} /></label>
          <label>Heating needed in winter
            <select value={cfg.heating_required === null ? "" : String(cfg.heating_required)}
              onChange={(e) => set("heating_required", e.target.value === "" ? null : e.target.value === "true")}>
              <option value="">Not set</option><option value="true">Yes</option><option value="false">No</option>
            </select>
          </label>
          <label>Water pressure (bar)<input type="number" step="0.1" value={cfg.water_pressure_bar ?? ""}
            onChange={(e) => set("water_pressure_bar", num(e.target.value))} /></label>
          <label>Electricity supply
            <select value={cfg.electricity_supply ?? ""} onChange={(e) => set("electricity_supply", e.target.value || null)}>
              <option value="">Not set</option>
              <option value="single_phase_230v">Single-phase 230 V</option>
              <option value="three_phase_400v">Three-phase 400 V</option>
              <option value="off_grid">Off-grid</option>
            </select>
          </label>
          <label>Latitude<input type="number" step="0.01" value={cfg.latitude ?? ""}
            onChange={(e) => set("latitude", num(e.target.value))} /></label>
          <label>Longitude<input type="number" step="0.01" value={cfg.longitude ?? ""}
            onChange={(e) => set("longitude", num(e.target.value))} /></label>
          <div className="stat">Air volume (estimate)<b>{cfg.height_m ? `${(cfg.length_m * cfg.width_m * cfg.height_m).toFixed(0)} m³` : "needs height"}</b></div>
        </div>
        <button className="primary" onClick={save}>Save</button>
        {mode === "advanced" && inputs && (
          <div className="table-wrap" style={{ marginTop: 16 }}>
            <table>
              <thead><tr><th>Input</th><th>Status</th><th>Needed for</th></tr></thead>
              <tbody>{inputs.items.map((i) => (
                <tr key={i.key}><td>{i.label}</td><td>{i.provided ? "provided" : "missing"}</td>
                  <td>{i.needed_for.join(", ")}</td></tr>))}</tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
