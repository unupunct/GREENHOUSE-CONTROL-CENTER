import { useState } from "react";
import { api, usePoll } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
const SECTION_LABEL: Record<string, string> = { what: "What it does", how: "How it works", why: "Why it is needed", wiring: "Wiring", installation: "Installation",
  configuration: "Configuration", calibration: "Calibration", troubleshooting: "Troubleshooting", maintenance: "Maintenance" };
const IFACES = ["i2c", "1wire", "uart", "spi", "gpio_in", "gpio_out", "rs485", "analog_voltage", "analog_420ma", "pulse", "contact", "power_dc", "power_ac"];
const YES: Record<string, string> = { directly: "Yes, directly", with_adapter: "Yes, with an adapter", not_applicable: "No data connection" };

function Compat({ c }: { c: J }) {
  return (
    <div className="panel">
      <b>Compatibility</b>
      <p>{c.summary}</p>
      <ul className="checks">
        <li>Can it connect to the Raspberry Pi? <b>{YES[c.can_connect_to_pi]}</b>{c.adapters_needed.length > 0 && ` — ${c.adapters_needed.join("; ")}`}</li>
        <li>Protocol: <b>{c.protocols.join(", ")}</b> · needs an ADC: <b>{c.needs_adc ? "yes" : "no"}</b></li>
        <li>External power: <b>{c.needs_external_power ? "yes" : "no"}</b> ({c.supply}) · ESP32: <b>{c.esp32}</b></li>
        {c.supported_by_application && <li>Driver in this application: <code>{c.supported_by_application.driver}</code> {c.supported_by_application.hardware_tested ? "(tested on hardware)" : "(not yet tested on hardware)"}</li>}
      </ul>
      {c.warnings.map((w: string) => <p key={w} className="muted">⚠ {w}</p>)}
    </div>
  );
}

function Checker() {
  const [ifs, setIfs] = useState<string[]>(["analog_voltage"]);
  const [ext, setExt] = useState(false);
  const [res, setRes] = useState<J | null>(null);
  return (
    <section className="card">
      <h2>Compatibility checker for any device</h2>
      <p className="muted">Not in the list? Tell it how the device connects.</p>
      <div className="row">{IFACES.map((i) => <label key={i} className="check"><input type="checkbox" checked={ifs.includes(i)} onChange={(e) => setIfs(e.target.checked ? [...ifs, i] : ifs.filter((x) => x !== i))} />{i}</label>)}
        <label className="check"><input type="checkbox" checked={ext} onChange={(e) => setExt(e.target.checked)} />needs external power</label>
        <button className="pill" disabled={!ifs.length} onClick={async () => setRes(await api.post<J>("/api/encyclopedia/compatibility/check", { interface: ifs, external_power: ext }))}>Check</button></div>
      {res && <Compat c={res} />}
    </section>
  );
}

function Page({ id }: { id: string }) {
  const [p] = usePoll<J>(`/api/encyclopedia/${id}`, 0);
  if (!p) return null;
  return (
    <section className="card">
      <h2>{p.name} <span className="muted" style={{ fontWeight: 400 }}>· {p.category.title}</span></h2>
      <p>{p.summary}</p>
      {p.notes && <div className="banner warning">{p.notes}</div>}
      <Compat c={p.compatibility} />
      <div className="panel"><b>Specifications</b>
        {p.specs.length ? <ul className="checks">{p.specs.map((s: J) => <li key={s.name}>{s.name}: <b>{s.value}</b></li>)}</ul> : <span className="muted">No figures given.</span>}
        <span className="muted">{p.spec_note}</span></div>
      <div className="panel"><b>Recommended models and alternatives</b>
        <ul className="checks">{p.models.map((m: J) => <li key={m.name}><b>{m.name}</b> {m.maker && m.maker !== "-" && `(${m.maker})`} {m.note && <span className="muted">— {m.note}</span>}</li>)}</ul>
        {p.alternatives.length > 0 && <span className="muted">Alternatives: {p.alternatives.join("; ")}</span>}</div>
      {Object.entries(p.sections).map(([k, v]) => <div key={k}><h3>{SECTION_LABEL[k]}</h3>
        {Array.isArray(v) ? <ul className="checks">{(v as string[]).map((x) => <li key={x}>• {x}</li>)}</ul> : <p>{v as string}</p>}</div>)}
      <h3>Replacement</h3><p>{p.replacement.interval} <span className="muted">(basis: {p.replacement.basis})</span></p>
      <h3>Purchase links and prices</h3>
      {p.purchase.offers.length ? <ul className="checks">{p.purchase.offers.map((o: J, i: number) => <li key={i}>{o.supplier}: <b>{o.price_ron_incl_vat} RON</b> incl. VAT ({o.status}) · {o.availability} · checked {new Date(o.checked_at * 1000).toLocaleDateString()}
        {o.url && <> · <a href={o.url} target="_blank" rel="noreferrer">product page</a></>}</li>)}</ul> : <p className="muted">No price recorded.</p>}
      <p className="muted">{p.purchase.note}</p>
      {p.used_in_your_system.length > 0 && <p><b>Used in your system:</b> {p.used_in_your_system.join(", ")}</p>}
    </section>
  );
}

export default function EncyclopediaPage() {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [sel, setSel] = useState("rpi5");
  const [d] = usePoll<J>(`/api/encyclopedia?q=${encodeURIComponent(q)}${cat ? `&category=${cat}` : ""}`, 0);
  return (
    <>
      <section className="card">
        <h2>Hardware encyclopedia</h2>
        <div className="row"><input placeholder="Search (e.g. modbus, pump, pH)…" value={q} onChange={(e) => setQ(e.target.value)} />
          <select value={cat} onChange={(e) => setCat(e.target.value)}><option value="">All categories</option>{d?.categories.map((c: J) => <option key={c.id} value={c.id}>{c.title} ({c.count})</option>)}</select></div>
        <div className="row" style={{ marginTop: 8 }}>{d?.items.map((i: J) => <button key={i.id} className={sel === i.id ? "pill on" : "pill"} onClick={() => setSel(i.id)} title={i.summary}>{i.name}</button>)}
          {d && d.items.length === 0 && <span className="muted">Nothing matches.</span>}</div>
      </section>
      <Page key={sel} id={sel} />
      <Checker />
    </>
  );
}
