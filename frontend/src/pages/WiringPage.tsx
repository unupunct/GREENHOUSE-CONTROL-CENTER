import { useState } from "react";
import { api, usePoll } from "../api";
import Mermaid from "../Mermaid";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;

export default function WiringPage() {
  const [d] = usePoll<J>("/api/wiring/diagrams", 0);
  const [mb] = usePoll<J[]>("/api/wiring/modbus", 0);
  const [gpio, , reloadGpio] = usePoll<J>("/api/wiring/gpio", 0);
  const [tab, setTab] = useState<"architecture" | "power" | "rs485">("architecture");
  const [rows, setRows] = useState<J[] | null>(null);
  const [msg, setMsg] = useState("");
  if (!d || !gpio) return <p className="muted">Loading…</p>;
  const assigned: J[] = rows ?? gpio.assigned;

  return (
    <>
      <section className="card">
        <div className="card-head"><h2>Diagrams</h2>
          <div className="row">{(["architecture", "power", "rs485"] as const).map((t) => (
            <button key={t} className={tab === t ? "pill on" : "pill"} onClick={() => setTab(t)}>
              {t === "architecture" ? "System" : t === "power" ? "Power & protection" : "RS485 bus"}</button>))}</div></div>
        <Mermaid code={d[tab]} />
        <p className="muted">{d.note}</p>
        {tab === "power" && <p className="muted">Mains work must be done by a qualified electrician. Never connect mains voltage to Raspberry Pi GPIO or to hobby relay boards.</p>}
        {tab === "rs485" && <ul className="checks muted">
          <li>• A/B twisted pair, daisy-chain only; 120 Ω termination at the two physical ends only.</li>
          <li>• One bias point (often built into the USB adapter); shield earthed at one end.</li>
          <li>• Unique slave addresses per bus. Details: docs/MODBUS_SETUP.md.</li></ul>}
      </section>

      <section className="card">
        <h2>Modbus address table</h2>
        {mb && mb.length ? <div className="table-wrap"><table>
          <thead><tr><th>Bus</th><th>Slave</th><th>Func</th><th>Register</th><th>Type</th><th>Sensor</th></tr></thead>
          <tbody>{mb.map((r) => <tr key={r.sensor_id}><td>{r.bus}</td><td>{r.slave}</td><td>{r.function}</td><td>{r.register}</td><td>{r.datatype}</td><td>{r.sensor_id} <span className="muted">({r.name})</span></td></tr>)}</tbody>
        </table></div> : <p className="muted">No Modbus sensors registered yet (Hardware page).</p>}
      </section>

      <section className="card">
        <h2>Raspberry Pi GPIO assignment</h2>
        <p className="muted">{gpio.note}</p>
        <div className="table-wrap"><table>
          <thead><tr><th>BCM</th><th>Header pin</th><th>Function</th><th>Used by</th></tr></thead>
          <tbody>{gpio.fixed.map((p: J) => <tr key={p.bcm}><td>{p.bcm}</td><td>{p.pin}</td><td>{p.function}</td><td>{p.used_by}</td></tr>)}</tbody>
        </table></div>
        <h3>Your assignments</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>BCM</th><th>Function</th><th>Device / note</th><th /></tr></thead>
          <tbody>{assigned.map((r, i) => (
            <tr key={i}>
              <td><input size={4} type="number" value={r.bcm} onChange={(e) => setRows(assigned.map((x, j) => j === i ? { ...x, bcm: Number(e.target.value) } : x))} /></td>
              <td><input value={r.function} onChange={(e) => setRows(assigned.map((x, j) => j === i ? { ...x, function: e.target.value } : x))} /></td>
              <td><input value={r.device ?? ""} onChange={(e) => setRows(assigned.map((x, j) => j === i ? { ...x, device: e.target.value } : x))} /></td>
              <td><button className="pill" onClick={() => setRows(assigned.filter((_, j) => j !== i))}>Remove</button></td>
            </tr>))}</tbody>
        </table></div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="pill" onClick={() => setRows([...assigned, { bcm: 17, function: "", device: "" }])}>Add</button>
          <button className="primary" onClick={async () => {
            try { await api.put("/api/wiring/gpio", assigned); setRows(null); reloadGpio(); setMsg("Saved."); }
            catch (e) { setMsg(String(e).replace(/^Error: \d+ /, "")); }
          }}>Save</button><span className="muted">{msg}</span>
        </div>
      </section>
    </>
  );
}
