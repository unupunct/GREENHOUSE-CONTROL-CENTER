import { useState } from "react";
import { usePoll } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;

export default function ManualPage() {
  const [kind, setKind] = useState("manual");
  const [tier, setTier] = useState("");
  const q = `kind=${kind}${tier ? `&tier=${tier}` : ""}`;
  const [p] = usePoll<J>(`/api/manual/preview?${q}`, 0);
  return (
    <section className="card">
      <h2>Installation manual</h2>
      <p className="muted">Generated from the equipment and settings registered right now: connection tables, Modbus addresses, GPIO pins, outputs, zones, calibration, commissioning and maintenance. If no real hardware is registered it says so instead of printing generic instructions.</p>
      <div className="row">
        <select value={kind} onChange={(e) => setKind(e.target.value)}><option value="manual">Full manual</option><option value="checklist">Printable checklist</option></select>
        <select value={tier} onChange={(e) => setTier(e.target.value)}><option value="">Equipment tier: as planned</option><option value="low">low</option><option value="recommended">recommended</option><option value="professional">professional</option></select>
        {["pdf", "html", "md"].map((f) => <a key={f} className="pill" href={`/api/manual/download.${f}?${q}`}>Download {f === "md" ? "Markdown" : f.toUpperCase()}</a>)}
      </div>
      {p && <>
        <h3>{p.title}</h3>
        <p>{p.real_sensors} real sensor(s), {p.real_outputs} real output(s); {p.simulated_sensors} simulated sensor(s) and {p.simulated_outputs} simulated output(s) are marked as such.</p>
        <p className="muted">{p.note}</p>
        <ol>{p.sections.map((s: J) => <li key={s.heading}>{s.heading}</li>)}</ol>
      </>}
      <p className="muted">The HTML version works offline and prints cleanly; the PDF includes a connection diagram. Regenerate after any change and keep a printed copy with the control cabinet.</p>
    </section>
  );
}
