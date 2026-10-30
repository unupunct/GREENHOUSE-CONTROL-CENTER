import { useState } from "react";
import { api, usePoll, type Sensor } from "../api";

interface Driver { name: string; label: string; protocol: string; kinds: string[] | null; hardware_tested: boolean; address_help: string }
interface Drivers { drivers: Driver[]; kinds: string[]; zones: string[] }
interface Bus { id: string; type: string; port: string; baudrate: number; parity: string; stopbits: number; timeout_s: number }
interface FullSensor extends Sensor { address: Record<string, unknown>; min_valid: number | null; max_valid: number | null;
  cal_gain: number; cal_offset: number; raw: number | null; protocol: string }

const TEMPLATES: Record<string, object> = {
  modbus_rtu: { bus: "rs485_1", slave: 1, function: 3, register: 0, datatype: "int16", word_order: "big", scale: 1, offset: 0 },
  ds18b20: { device_id: "28-000000000000" },
  sht3x: { bus: 1, i2c_address: 68 },
  simulated: {},
};

const errText = (e: unknown) => String(e).replace(/^Error: \d+ /, "");

function BusEditor() {
  const [buses, , reload] = usePoll<Bus[]>("/api/hardware/buses", 0);
  const [ports] = usePoll<{ ports: { device: string; description: string }[] }>("/api/hardware/serial-ports", 0);
  const [draft, setDraft] = useState<Bus[] | null>(null);
  const [msg, setMsg] = useState("");
  const [scan, setScan] = useState({ bus: "", start: 1, end: 10, function: 3, register: 0 });
  const [found, setFound] = useState<unknown[] | null>(null);
  const list = draft ?? buses ?? [];
  const edit = (i: number, patch: Partial<Bus>) => setDraft(list.map((b, j) => (j === i ? { ...b, ...patch } : b)));

  return (
    <section className="card">
      <h2>RS485 / Modbus buses</h2>
      <p className="muted">One bus = one USB-RS485 adapter. Serial ports found: {ports?.ports.map((p) => p.device).join(", ") || "none"}</p>
      <div className="table-wrap"><table>
        <thead><tr><th>ID</th><th>Port</th><th>Baud</th><th>Parity</th><th>Stop</th><th>Timeout s</th><th /></tr></thead>
        <tbody>{list.map((b, i) => (
          <tr key={i}>
            <td><input size={9} value={b.id} onChange={(e) => edit(i, { id: e.target.value })} /></td>
            <td><input size={12} value={b.port} onChange={(e) => edit(i, { port: e.target.value })} placeholder="/dev/ttyUSB0" /></td>
            <td><input size={6} type="number" value={b.baudrate} onChange={(e) => edit(i, { baudrate: Number(e.target.value) })} /></td>
            <td><select value={b.parity} onChange={(e) => edit(i, { parity: e.target.value })}><option>N</option><option>E</option><option>O</option></select></td>
            <td><select value={b.stopbits} onChange={(e) => edit(i, { stopbits: Number(e.target.value) })}><option>1</option><option>2</option></select></td>
            <td><input size={4} type="number" step="0.1" value={b.timeout_s} onChange={(e) => edit(i, { timeout_s: Number(e.target.value) })} /></td>
            <td><button className="pill" onClick={() => setDraft(list.filter((_, j) => j !== i))}>Remove</button></td>
          </tr>))}</tbody>
      </table></div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="pill" onClick={() => setDraft([...list, { id: `rs485_${list.length + 1}`, type: "modbus_rtu", port: "", baudrate: 9600, parity: "N", stopbits: 1, timeout_s: 1 }])}>Add bus</button>
        <button className="primary" disabled={!draft} onClick={async () => {
          try { await api.put("/api/hardware/buses", list); setDraft(null); reload(); setMsg("Saved."); } catch (e) { setMsg(errText(e)); }
        }}>Save buses</button><span className="muted">{msg}</span>
      </div>

      <h3>Scan for devices</h3>
      <p className="muted">Reads one register from each address. Choose a register that exists on your device. At most 32 addresses per scan;
        polling on the bus pauses meanwhile. A "crc_error" that repeats can mean two devices share an address.</p>
      <div className="row">
        <select value={scan.bus} onChange={(e) => setScan({ ...scan, bus: e.target.value })}>
          <option value="">Bus…</option>{(buses ?? []).map((b) => <option key={b.id}>{b.id}</option>)}</select>
        {(["start", "end", "register"] as const).map((k) => (
          <label key={k} className="inline">{k}<input size={5} type="number" value={scan[k]} onChange={(e) => setScan({ ...scan, [k]: Number(e.target.value) })} /></label>))}
        <select value={scan.function} onChange={(e) => setScan({ ...scan, function: Number(e.target.value) })}>
          <option value={3}>func 3 holding</option><option value={4}>func 4 input</option></select>
        <button className="pill" disabled={!scan.bus} onClick={async () => {
          setFound(null);
          try { const { bus, ...body } = scan; setFound((await api.post<{ found: unknown[] }>(`/api/hardware/buses/${bus}/scan`, body)).found); }
          catch (e) { setFound([{ result: errText(e) }]); }
        }}>Scan</button>
      </div>
      {found && <pre className="out">{found.length ? JSON.stringify(found, null, 1) : "No device answered."}</pre>}
    </section>
  );
}

function CalibrationPanel({ s, onDone }: { s: FullSensor; onDone: () => void }) {
  const [ref, setRef] = useState("");
  const [two, setTwo] = useState({ raw1: "", ref1: "", raw2: "", ref2: "" });
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const send = async (body: object) => {
    try { await api.post(`/api/sensors/${s.id}/calibration`, { note, ...body }); setMsg("Calibration saved."); onDone(); }
    catch (e) { setMsg(errText(e)); }
  };
  return (
    <div className="panel">
      <b>Calibrate {s.id}</b> <span className="muted">current: calibrated = {s.cal_gain.toFixed(4)} × raw + {s.cal_offset.toFixed(4)} · live raw {s.raw ?? "–"}</span>
      <div className="row">
        <label className="inline">Reference now<input size={7} value={ref} onChange={(e) => setRef(e.target.value)} /></label>
        <button className="pill" onClick={() => send({ method: "one_point", reference: Number(ref) })}>One-point (offset)</button>
      </div>
      <div className="row">
        {(["raw1", "ref1", "raw2", "ref2"] as const).map((k) => (
          <label key={k} className="inline">{k}<input size={6} value={two[k]} onChange={(e) => setTwo({ ...two, [k]: e.target.value })} /></label>))}
        <button className="pill" onClick={() => send({ method: "two_point", raw1: +two.raw1, ref1: +two.ref1, raw2: +two.raw2, ref2: +two.ref2 })}>Two-point</button>
      </div>
      <div className="row">
        <label className="inline">Note<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="reference instrument / buffer used" /></label>
        <button className="pill" onClick={() => send({ method: "reset" })}>Reset</button> <span className="muted">{msg}</span>
      </div>
    </div>
  );
}

function AddSensor({ drivers, onDone }: { drivers: Drivers; onDone: () => void }) {
  const [f, setF] = useState({ id: "", name: "", kind: "temperature", zone: "greenhouse", unit: "°C", driver: "modbus_rtu", min: "", max: "" });
  const [addr, setAddr] = useState(JSON.stringify(TEMPLATES.modbus_rtu, null, 1));
  const [msg, setMsg] = useState("");
  const drv = drivers.drivers.find((d) => d.name === f.driver);
  return (
    <section className="card">
      <h2>Add sensor</h2>
      <div className="form">
        <label>ID (a-z 0-9 _)<input value={f.id} onChange={(e) => setF({ ...f, id: e.target.value })} /></label>
        <label>Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label>Driver<select value={f.driver} onChange={(e) => { setF({ ...f, driver: e.target.value }); setAddr(JSON.stringify(TEMPLATES[e.target.value] ?? {}, null, 1)); }}>
          {drivers.drivers.map((d) => <option key={d.name} value={d.name}>{d.label}</option>)}</select></label>
        <label>Measures<select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          {(drv?.kinds ?? drivers.kinds).map((k) => <option key={k}>{k}</option>)}</select></label>
        <label>Zone<select value={f.zone} onChange={(e) => setF({ ...f, zone: e.target.value })}>
          {drivers.zones.map((z) => <option key={z}>{z}</option>)}</select></label>
        <label>Unit<input value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} /></label>
        <label>Valid min<input type="number" value={f.min} onChange={(e) => setF({ ...f, min: e.target.value })} /></label>
        <label>Valid max<input type="number" value={f.max} onChange={(e) => setF({ ...f, max: e.target.value })} /></label>
      </div>
      <label>Address (JSON)<textarea rows={7} value={addr} onChange={(e) => setAddr(e.target.value)} /></label>
      <p className="muted">{drv?.address_help} {drv && !drv.hardware_tested && "This driver has not yet been tested on physical hardware."}</p>
      <button className="primary" onClick={async () => {
        try {
          await api.post("/api/sensors", { id: f.id, name: f.name, kind: f.kind, zone: f.zone, unit: f.unit, driver: f.driver,
            address: JSON.parse(addr), min_valid: f.min === "" ? null : +f.min, max_valid: f.max === "" ? null : +f.max });
          setMsg("Added."); onDone();
        } catch (e) { setMsg(errText(e)); }
      }}>Add sensor</button> <span className="muted">{msg}</span>
    </section>
  );
}

export default function HardwarePage() {
  const [sensors, , reload] = usePoll<FullSensor[]>("/api/sensors", 5000);
  const [drivers] = usePoll<Drivers>("/api/hardware/drivers", 0);
  const [results, setResults] = useState<Record<string, string>>({});
  const [cal, setCal] = useState<string | null>(null);

  return (
    <>
      <BusEditor />
      <section className="card">
        <h2>Registered sensors</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>ID</th><th>Driver</th><th>Raw</th><th>Calibrated</th><th>Cal.</th><th>Status</th><th /></tr></thead>
          <tbody>{(sensors ?? []).map((s) => (
            <tr key={s.id}>
              <td><code>{s.id}</code></td><td>{s.driver}</td>
              <td>{s.raw ?? "–"}</td><td>{s.value === null ? "–" : `${s.value} ${s.unit}`}</td>
              <td>{s.cal_gain !== 1 || s.cal_offset !== 0 ? "yes" : "–"}</td>
              <td><span className={`dot-s ${s.status}`} /> {s.status}</td>
              <td className="row">
                <button className="pill" onClick={async () => {
                  const r = await api.post<{ ok: boolean; raw?: number; calibrated?: number; error?: string; elapsed_ms?: number }>(`/api/sensors/${s.id}/test-read`);
                  setResults({ ...results, [s.id]: r.ok ? `raw ${r.raw} → ${r.calibrated} (${r.elapsed_ms} ms)` : `✗ ${r.error}` });
                }}>Test</button>
                <button className="pill" onClick={() => setCal(cal === s.id ? null : s.id)}>Calibrate</button>
                <button className="pill" onClick={async () => {
                  if (confirm(`Delete ${s.id} AND all its stored history?`)) { await fetch(`/api/sensors/${s.id}`, { method: "DELETE" }); reload(); }
                }}>Delete</button>
                {results[s.id] && <span className="muted">{results[s.id]}</span>}
              </td>
            </tr>))}</tbody>
        </table></div>
        {sensors?.filter((s) => s.id === cal).map((s) => <CalibrationPanel key={s.id} s={s} onDone={reload} />)}
      </section>
      {drivers && <AddSensor drivers={drivers} onDone={reload} />}
    </>
  );
}
