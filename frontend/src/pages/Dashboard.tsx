import { useState } from "react";
import { api, usePoll, type Point, type Sensor, type Vpd } from "../api";
import LineChart from "../LineChart";
import { useEffect } from "react";

const RANGES: [string, number][] = [["1 h", 1], ["6 h", 6], ["24 h", 24], ["7 d", 168]];

function Tile({ label, value, unit, note, state }: {
  label: string; value: string; unit?: string; note?: string; state?: string;
}) {
  return (
    <div className={`tile ${state ?? ""}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}<span className="unit">{unit}</span></div>
      {note && <div className="tile-note">{note}</div>}
    </div>
  );
}

function mean(xs: Sensor[]): number | null {
  const v = xs.filter((s) => s.value !== null).map((s) => s.value as number);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}
const fmt = (v: number | null, d = 1) => (v === null ? "–" : v.toFixed(d));

export default function Dashboard({ mode }: { mode: "basic" | "advanced" }) {
  const [sensors] = usePoll<Sensor[]>("/api/sensors", 5000);
  const [vpd] = usePoll<Vpd>("/api/climate/vpd", 5000);
  const [sel, setSel] = useState("gh_temp_1");
  const [hours, setHours] = useState(24);
  const [pts, setPts] = useState<Point[]>([]);
  const [useVpd, setUseVpd] = useState(false);

  useEffect(() => {
    const path = useVpd
      ? `/api/climate/vpd/history?hours=${hours}`
      : `/api/readings/history?sensor_id=${sel}&hours=${hours}`;
    const load = () => api.get<{ points: Point[] }>(path).then((r) => setPts(r.points)).catch(() => setPts([]));
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [sel, hours, useVpd]);

  if (!sensors) return <p className="muted">Loading…</p>;
  const by = (zone: string, kind: string) => sensors.filter((s) => s.zone === zone && s.kind === kind);
  const find = (id: string) => sensors.find((s) => s.id === id);
  const selSensor = find(sel);
  const stale = sensors.filter((s) => s.enabled && s.status !== "ok").length;

  return (
    <>
      <section className="tiles">
        <Tile label="Air temperature" value={fmt(mean(by("greenhouse", "temperature")))} unit="°C" />
        <Tile label="Air humidity" value={fmt(mean(by("greenhouse", "humidity")), 0)} unit="%" />
        <Tile label="VPD" value={vpd?.available ? vpd.vpd_kpa!.toFixed(2) : "–"} unit="kPa"
          note="Leaf temp assumed = air temp" />
        <Tile label="CO₂" value={fmt(mean(by("greenhouse", "co2")), 0)} unit="ppm" />
        <Tile label="Soil moisture" value={fmt(mean(by("soil", "soil_moisture")), 0)} unit="%" />
        <Tile label="Nutrient tank" value={fmt(mean(by("hydroponic", "water_level")), 0)} unit="%" />
        <Tile label="Outdoor" value={fmt(mean(by("outdoor", "temperature")))} unit="°C" />
        <Tile label="Sensors" value={stale ? `${stale} need attention` : "All OK"}
          state={stale ? "warn" : "good"} />
      </section>

      <section className="card">
        <div className="card-head">
          <h2>History</h2>
          <div className="row">
            {mode === "advanced" ? (
              <select value={useVpd ? "__vpd" : sel}
                onChange={(e) => e.target.value === "__vpd" ? setUseVpd(true) : (setUseVpd(false), setSel(e.target.value))}>
                <option value="__vpd">VPD (calculated)</option>
                {sensors.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            ) : (
              <select value={useVpd ? "__vpd" : sel}
                onChange={(e) => e.target.value === "__vpd" ? setUseVpd(true) : (setUseVpd(false), setSel(e.target.value))}>
                <option value="gh_temp_1">Temperature</option>
                <option value="gh_rh_1">Humidity</option>
                <option value="__vpd">VPD</option>
                <option value="gh_co2_1">CO₂</option>
                <option value="soil_moist_1">Soil moisture</option>
              </select>
            )}
            {RANGES.map(([l, h]) => (
              <button key={h} className={hours === h ? "pill on" : "pill"} onClick={() => setHours(h)}>{l}</button>
            ))}
          </div>
        </div>
        <LineChart points={pts} unit={useVpd ? "kPa" : selSensor?.unit ?? ""} />
      </section>

      {mode === "advanced" && (
        <section className="card">
          <h2>Sensor registry</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>Name</th><th>Zone</th><th>Protocol</th><th>Driver</th><th>Value</th><th>Status</th></tr></thead>
              <tbody>
                {sensors.map((s) => (
                  <tr key={s.id} onClick={() => { setUseVpd(false); setSel(s.id); }} className="click">
                    <td><code>{s.id}</code></td><td>{s.name}</td><td>{s.zone}</td><td>{s.protocol}</td>
                    <td>{s.driver}{s.simulated ? " (sim)" : ""}</td>
                    <td>{s.value === null ? "–" : `${s.value} ${s.unit}`}</td>
                    <td><span className={`dot-s ${s.status}`} /> {s.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
