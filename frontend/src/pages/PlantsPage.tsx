import { useEffect, useState } from "react";
import { api, usePoll } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
const errText = (e: unknown) => String(e).replace(/^Error: \d+ /, "").replace(/^\{"detail":"?|"?\}$/g, "");
const rangeTxt = (r: J | null | undefined, unit = "") => (r ? `${r.min}–${r.max}${unit}` : "–");

type Field = { path: string[]; label: string; step?: number };
const FIELDS: Field[] = [
  { path: ["temperature_c", "day_min"], label: "Day min °C" }, { path: ["temperature_c", "day_max"], label: "Day max °C" },
  { path: ["temperature_c", "night_min"], label: "Night min °C" }, { path: ["temperature_c", "night_max"], label: "Night max °C" },
  { path: ["humidity_rh", "min"], label: "RH min %" }, { path: ["humidity_rh", "max"], label: "RH max %" },
  { path: ["vpd_kpa", "min"], label: "VPD min kPa", step: 0.05 }, { path: ["vpd_kpa", "max"], label: "VPD max kPa", step: 0.05 },
  { path: ["light", "dli_mol_m2_day", "min"], label: "DLI min mol/m²/day" }, { path: ["light", "dli_mol_m2_day", "max"], label: "DLI max mol/m²/day" },
  { path: ["soil", "ph", "min"], label: "Soil pH min", step: 0.1 }, { path: ["soil", "ph", "max"], label: "Soil pH max", step: 0.1 },
  { path: ["hydroponic", "ph", "min"], label: "Hydro pH min", step: 0.1 }, { path: ["hydroponic", "ph", "max"], label: "Hydro pH max", step: 0.1 },
  { path: ["hydroponic", "ec_ms_cm", "min"], label: "Hydro EC min mS/cm", step: 0.1 }, { path: ["hydroponic", "ec_ms_cm", "max"], label: "Hydro EC max mS/cm", step: 0.1 },
  { path: ["hydroponic", "solution_temp_c", "min"], label: "Solution °C min" }, { path: ["hydroponic", "solution_temp_c", "max"], label: "Solution °C max" },
  { path: ["water", "l_per_m2_day"], label: "Water L/m²/day (yours)", step: 0.1 },
];
const get = (o: J, p: string[]) => p.reduce((a, k) => (a == null ? a : a[k]), o);
const nest = (p: string[], v: any): J => p.reduceRight((acc, k) => ({ [k]: acc }), v);
const merge = (a: J, b: J): J => { const o = { ...a }; for (const [k, v] of Object.entries(b)) o[k] = v && typeof v === "object" && !Array.isArray(v) ? merge(o[k] ?? {}, v) : v; return o; };

function Profile({ id, reload }: { id: string; reload: () => void }) {
  const [d, , reloadP] = usePoll<J>(`/api/plants/${id}`, 0);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [newId, setNewId] = useState("");
  useEffect(() => { setEdit({}); setMsg(""); }, [id]);
  if (!d) return null;
  const p = d.profile, changed: string[] = d.user_changed_fields;
  const isYours = (path: string[]) => changed.some((c) => c === path.join(".") || c.startsWith("("));
  const save = async () => {
    try {
      let patch: J = {};
      for (const f of FIELDS) { const k = f.path.join("."); if (edit[k] !== undefined && edit[k] !== "") patch = merge(patch, nest(f.path, Number(edit[k]))); }
      if (p.custom) await api.put(`/api/plants/${id}`, merge(p, patch)); else await api.put(`/api/plants/${id}/override`, patch);
      setEdit({}); setMsg("Saved."); reloadP(); reload();
    } catch (e) { setMsg(errText(e)); }
  };
  const List = ({ t, items }: { t: string; items: string[] }) => <p><b>{t}:</b> {items.length ? items.join(", ") : "–"}</p>;
  return (
    <section className="card">
      <h2>{p.name} <span className="muted" style={{ fontWeight: 400 }}><i>{p.latin}</i> · {p.category}</span></h2>
      <div className="banner warning">{d.provenance}</div>
      <p>Day <b>{p.temperature_c.day_min}–{p.temperature_c.day_max} °C</b> · night <b>{p.temperature_c.night_min}–{p.temperature_c.night_max} °C</b> · RH <b>{rangeTxt(p.humidity_rh, " %")}</b> ·
        VPD <b>{rangeTxt(p.vpd_kpa, " kPa")}</b> · DLI <b>{rangeTxt(p.light.dli_mol_m2_day, " mol/m²/day")}</b></p>
      <div className="form">
        <div className="panel"><b>Soil growing</b><span className="muted">pH {rangeTxt(p.soil.ph)}</span><span className="muted">{p.soil.notes}</span></div>
        <div className="panel"><b>Hydroponic growing</b><span className="muted">pH {rangeTxt(p.hydroponic.ph)} · EC {rangeTxt(p.hydroponic.ec_ms_cm, " mS/cm")} · solution {rangeTxt(p.hydroponic.solution_temp_c, " °C")}</span><span className="muted">{p.hydroponic.notes}</span></div>
        <div className="panel"><b>Germination</b><span className="muted">{p.germination.temp_c ? `${rangeTxt(p.germination.temp_c, " °C")}, ${rangeTxt(p.germination.days, " days")}. ` : ""}{p.germination.notes}</span></div>
        <div className="panel"><b>Water</b><span className="muted">{p.water.l_per_m2_day ?? "not provided"} L/m²/day. {p.water.note}</span></div>
      </div>
      <p><b>Planting:</b> {p.planting}</p><p><b>Transplanting:</b> {p.transplanting}</p>
      <p><b>Growth stages:</b> {p.growth_stages.map((s: J) => s.name).join(" → ")}</p>
      <ul className="checks">{p.growth_stages.map((s: J) => <li key={s.name} className="muted"><b>{s.name}:</b> {s.notes}</li>)}</ul>
      <p><b>Harvest:</b> {p.harvest}</p>
      <List t="Common pests" items={p.pests} /><List t="Diseases and disorders" items={p.diseases} />
      <p><b>Nutrients:</b> {p.nutrients}</p>
      {p.notes && <p className="muted">{p.notes}</p>}

      <h3>Your values</h3>
      <p className="muted">Change any range for your cultivar or system. Edited fields are marked <span className="yours">yours</span>; the rest remain general guidance.</p>
      <div className="form">{FIELDS.map((f) => { const k = f.path.join("."); const cur = get(p, f.path);
        return <label key={k}>{f.label}{isYours(f.path) && <span className="yours">yours</span>}
          <input type="number" step={f.step ?? 1} placeholder={cur == null ? "" : String(cur)} value={edit[k] ?? ""} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} /></label>; })}</div>
      <div className="row">
        <button className="primary" onClick={save}>Save changes</button>
        {!p.custom && changed.length > 0 && <button className="pill" onClick={async () => { await fetch(`/api/plants/${id}/override`, { method: "DELETE" }); reloadP(); reload(); }}>Reset to general guidance</button>}
        {p.custom && <button className="pill" onClick={async () => { const r = await fetch(`/api/plants/${id}`, { method: "DELETE" }); if (!r.ok) setMsg(errText(await r.text())); else reload(); }}>Delete custom crop</button>}
        <span className="muted">{msg}</span>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <input placeholder="new crop id (a-z 0-9 _)" value={newId} onChange={(e) => setNewId(e.target.value)} />
        <button className="pill" onClick={async () => { try { await api.put(`/api/plants/${newId}`, { ...p, name: `${p.name} (copy)` }); setNewId(""); reload(); setMsg("Custom crop created."); } catch (e) { setMsg(errText(e)); } }}>Duplicate as my own crop</button>
      </div>
    </section>
  );
}

function Batches({ plants }: { plants: J[] }) {
  const [list, , reload] = usePoll<J[]>("/api/crops", 0);
  const [b, setB] = useState({ id: "", crop_id: "tomato", label: "", method: "soil", area_m2: "", planted_on: new Date().toISOString().slice(0, 10) });
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [kg, setKg] = useState({ date: new Date().toISOString().slice(0, 10), q: "" });
  const [status] = usePoll<J>(open ? `/api/crops/${open}/status` : "/api/health", 10000);
  return (
    <section className="card">
      <h2>Crop batches and harvest records</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Batch</th><th>Crop</th><th>Method</th><th>Planted</th><th>Area m²</th><th>Harvested kg</th><th>kg/m²</th><th>Status</th><th /></tr></thead>
        <tbody>{(list ?? []).map((x) => (
          <tr key={x.id}><td><code>{x.id}</code> {x.label}</td><td>{x.crop_id}</td><td>{x.method}</td><td>{x.planted_on}</td><td>{x.area_m2 ?? "–"}</td><td>{x.harvested_kg}</td><td>{x.yield_kg_per_m2 ?? "–"}</td><td>{x.status}</td>
            <td className="row"><button className="pill" onClick={() => setOpen(open === x.id ? null : x.id)}>Conditions</button>
              <button className="pill" onClick={async () => { await fetch(`/api/crops/${x.id}`, { method: "DELETE" }); reload(); }}>Delete</button></td></tr>))}</tbody>
      </table></div>
      {open && status?.checks && <div className="panel"><b>Live conditions vs {status.crop} profile ({status.method})</b>
        <div>{status.checks.map((c: J) => <span key={c.name} className={`chip ${c.status}`}>{c.name}: {c.value ?? "no data"}{c.value != null && c.unit} ({c.min ?? "–"}–{c.max ?? "–"}) · {c.status.replace("_", " ")}</span>)}</div>
        <div className="row"><input type="date" value={kg.date} onChange={(e) => setKg({ ...kg, date: e.target.value })} />
          <input size={6} type="number" placeholder="kg" value={kg.q} onChange={(e) => setKg({ ...kg, q: e.target.value })} />
          <button className="pill" onClick={async () => { try { await api.post(`/api/crops/${open}/harvests`, { date: kg.date, quantity_kg: Number(kg.q) }); setKg({ ...kg, q: "" }); reload(); } catch (e) { setMsg(errText(e)); } }}>Record harvest</button></div></div>}
      <h3>New batch</h3>
      <div className="form">
        <label>ID<input value={b.id} onChange={(e) => setB({ ...b, id: e.target.value })} /></label>
        <label>Crop<select value={b.crop_id} onChange={(e) => setB({ ...b, crop_id: e.target.value })}>{plants.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>Label<input value={b.label} onChange={(e) => setB({ ...b, label: e.target.value })} /></label>
        <label>Method<select value={b.method} onChange={(e) => setB({ ...b, method: e.target.value })}><option value="soil">soil</option><option value="hydroponic">hydroponic</option></select></label>
        <label>Area (m²)<input type="number" value={b.area_m2} onChange={(e) => setB({ ...b, area_m2: e.target.value })} /></label>
        <label>Planted on<input type="date" value={b.planted_on} onChange={(e) => setB({ ...b, planted_on: e.target.value })} /></label>
      </div>
      <button className="primary" onClick={async () => { try { await api.post("/api/crops", { ...b, area_m2: b.area_m2 ? Number(b.area_m2) : null }); setMsg("Added."); reload(); } catch (e) { setMsg(errText(e)); } }}>Add batch</button> <span className="muted">{msg}</span>
    </section>
  );
}

export default function PlantsPage() {
  const [list, , reload] = usePoll<J>("/api/plants", 0);
  const [sel, setSel] = useState("tomato");
  if (!list) return <p className="muted">Loading…</p>;
  return (
    <>
      <section className="card">
        <h2>Plant knowledgebase</h2>
        <p className="muted">{list.provenance}</p>
        <div className="row">{list.plants.map((p: J) => <button key={p.id} className={sel === p.id ? "pill on" : "pill"} onClick={() => setSel(p.id)}>{p.name}{p.modified && <span className="yours" style={{ color: "inherit" }}>*</span>}{p.custom && " ★"}</button>)}</div>
      </section>
      <Profile id={sel} reload={reload} />
      <Batches plants={list.plants} />
    </>
  );
}
