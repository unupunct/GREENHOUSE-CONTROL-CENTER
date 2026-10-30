import { useState } from "react";
import { usePoll, type Point, type Sensor } from "../api";
import LineChart from "../LineChart";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
const today = () => new Date().toISOString().slice(0, 10);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function DliBars({ d }: { d: J }) {
  const days: J[] = d.days.slice(-30);
  if (!days.length) return <p className="muted">No PAR history yet. DLI needs a PAR sensor that has been recording.</p>;
  const max = Math.max(1, ...days.map((x) => x.dli_mol_m2), d.target?.max ?? 0);
  const W = 640, H = 170, bw = (W - 40) / days.length;
  const y = (v: number) => 10 + (1 - v / max) * (H - 30);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart bars" role="img">
      {d.target && <><line className="t" x1={30} x2={W - 6} y1={y(d.target.min)} y2={y(d.target.min)} /><line className="t" x1={30} x2={W - 6} y1={y(d.target.max)} y2={y(d.target.max)} />
        <text x={32} y={y(d.target.max) - 3} className="axis">target {d.target.min}–{d.target.max}</text></>}
      <text x={2} y={y(max) + 4} className="axis">{max.toFixed(0)}</text><text x={2} y={H - 22} className="axis">0</text>
      {days.map((x, i) => (
        <g key={x.date}>
          <rect className={`bar ${!x.complete ? "part" : x.status === "low" || x.status === "high" ? "bad" : ""}`} x={34 + i * bw} width={Math.max(2, bw - 3)} y={y(x.dli_mol_m2)} height={H - 20 - y(x.dli_mol_m2)}>
            <title>{x.date}: {x.dli_mol_m2} mol/m² ({x.coverage_pct}% coverage){x.status ? ` · ${x.status}` : ""}</title></rect>
          {(i % Math.ceil(days.length / 8) === 0) && <text x={34 + i * bw} y={H - 6} className="axis">{x.date.slice(5)}</text>}
        </g>))}
    </svg>
  );
}

export default function AnalyticsPage() {
  const [crops] = usePoll<J>("/api/plants", 0);
  const [sensors] = usePoll<Sensor[]>("/api/sensors", 0);
  const [crop, setCrop] = useState("");
  const [hours, setHours] = useState(24);
  const q = crop ? `&crop_id=${crop}` : "";
  const [vpd] = usePoll<J>(`/api/analytics/vpd?hours=${hours}${q}`, 30000);
  const [dli] = usePoll<J>(`/api/analytics/dli?days=30${q}`, 60000);
  const [metric, setMetric] = useState("temperature");
  const [seasonal] = usePoll<J>(`/api/analytics/seasonal?metric=${metric}`, 0);
  const [period, setPeriod] = useState("week");
  const [date, setDate] = useState(today());
  const [rep] = usePoll<J>(`/api/analytics/report?period=${period}&date=${date}${q}`, 0);
  const [sid, setSid] = useState("gh_temp_1");
  const [days, setDays] = useState(7);
  const fmt = (s: J | null) => (s ? `${s.min} / ${s.avg} / ${s.max}` : "–");
  const years = seasonal ? Object.keys(seasonal.monthly_means) : [];

  return (
    <>
      <section className="card">
        <div className="card-head"><h2>VPD history</h2>
          <div className="row">
            <select value={crop} onChange={(e) => setCrop(e.target.value)}><option value="">Target: newest active batch</option>{crops?.plants.map((p: J) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
            {[[24, "24 h"], [168, "7 d"], [720, "30 d"]].map(([h, l]) => <button key={h} className={hours === h ? "pill on" : "pill"} onClick={() => setHours(h as number)}>{l}</button>)}
          </div></div>
        <LineChart points={(vpd?.points ?? []) as Point[]} unit="kPa" band={vpd?.target} />
        <p className="muted">{vpd?.crop ? `Shaded band: ${vpd.crop} target ${vpd.target.min}–${vpd.target.max} kPa (general guidance unless edited). ` : "No crop selected, so no target band. "}
          {vpd?.in_band && `${vpd.in_band.in_band_pct}% of samples in band, ${vpd.in_band.below_pct}% below, ${vpd.in_band.above_pct}% above. `}Leaf temperature is assumed equal to air temperature.</p>
      </section>

      <section className="card">
        <h2>Daily light integral (last 30 days)</h2>
        {dli && <DliBars d={dli} />}
        <p className="muted">{dli?.note} Grey bars are incomplete days. {dli?.crop && `Target lines: ${dli.crop}.`}</p>
      </section>

      <section className="card">
        <div className="card-head"><h2>Reports</h2>
          <div className="row">
            <select value={period} onChange={(e) => setPeriod(e.target.value)}><option value="day">Day</option><option value="week">Week (Mon–Sun)</option><option value="month">Month</option></select>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            <a className="pill" href={`/api/analytics/report.csv?period=${period}&date=${date}${q}`}>CSV</a>
            <a className="pill" href={`/api/analytics/report.pdf?period=${period}&date=${date}${q}`}>PDF</a>
          </div></div>
        {rep && <>
          <p className="muted">{rep.start} to {rep.end_exclusive} (end exclusive). Data completeness about {rep.data.completeness_pct}%.</p>
          <div className="table-wrap"><table>
            <thead><tr><th>Quantity</th><th>min / avg / max</th></tr></thead>
            <tbody>
              <tr><td>Air temperature °C</td><td>{fmt(rep.climate.temperature_c)}</td></tr><tr><td>Humidity %</td><td>{fmt(rep.climate.humidity_pct)}</td></tr>
              <tr><td>VPD kPa</td><td>{fmt(rep.climate.vpd_kpa)}</td></tr><tr><td>CO₂ ppm</td><td>{fmt(rep.climate.co2_ppm)}</td></tr>
              <tr><td>Outdoor °C</td><td>{fmt(rep.climate.outdoor_temperature_c)}</td></tr>
              <tr><td>Mean DLI (complete days)</td><td>{rep.light.dli_mean_complete_days ?? "–"} mol/m²/day</td></tr>
              <tr><td>Irrigation</td><td>{rep.irrigation.runs} runs · measured {rep.irrigation.total_measured_l} L · estimated {rep.irrigation.total_estimated_l} L</td></tr>
              <tr><td>Lighting</td><td>{rep.lighting.energy_kwh} kWh · {rep.lighting.lights_on_h} h on</td></tr>
              <tr><td>Alerts</td><td>{rep.alerts.count}</td></tr>
              {rep.targets && <tr><td>In {rep.targets.crop} VPD band</td><td>{rep.targets.vpd_band ? `${rep.targets.vpd_band.in_band_pct}%` : "–"}</td></tr>}
              {rep.condensation && <tr><td>Condensation indicator</td><td>{rep.condensation.dew_point_above_outdoor_pct}% of samples (indicator only)</td></tr>}
            </tbody></table></div></>}
      </section>

      <section className="card">
        <div className="card-head"><h2>Seasonal comparison</h2>
          <select value={metric} onChange={(e) => setMetric(e.target.value)}>{["temperature", "humidity", "co2", "outdoor_temperature", "dli"].map((m) => <option key={m}>{m}</option>)}</select></div>
        {years.length === 0 ? <p className="muted">No stored data yet. Comparison fills in as months accumulate (data older than the retention period is deleted).</p> :
          <div className="table-wrap"><table><thead><tr><th>Year</th>{MONTHS.map((m) => <th key={m}>{m}</th>)}</tr></thead>
            <tbody>{years.map((y) => <tr key={y}><td>{y}</td>{MONTHS.map((_, i) => <td key={i}>{seasonal!.monthly_means[y][String(i + 1).padStart(2, "0")] ?? ""}</td>)}</tr>)}</tbody></table></div>}
        <p className="muted">{seasonal?.note}</p>
      </section>

      <section className="card">
        <h2>Export raw measurements</h2>
        <div className="row">
          <select value={sid} onChange={(e) => setSid(e.target.value)}>{(sensors ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
          <label className="inline">days<input size={4} type="number" value={days} onChange={(e) => setDays(Number(e.target.value))} /></label>
          <a className="pill" href={`/api/analytics/export/measurements.csv?sensor_id=${sid}&days=${days}`}>Download CSV</a>
        </div>
      </section>
    </>
  );
}
