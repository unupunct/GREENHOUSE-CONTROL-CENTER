import { Fragment, useState } from "react";
import { api, usePoll } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
const ron = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toLocaleString("ro-RO", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const STATUS: Record<string, string> = { verified: "verified", user_estimate: "your estimate", none: "requires verification" };

function OfferForm({ line, suppliers, onDone }: { line: J; suppliers: J[]; onDone: () => void }) {
  const [f, setF] = useState({ supplier_id: suppliers[0]?.id ?? "", price_ron: "", includes_vat: true, url: "", availability: "", status: "user_estimate", note: "" });
  const [msg, setMsg] = useState("");
  return (
    <div className="panel">
      <b>Add a price for “{line.name}”</b>
      <p className="muted">Enter only what you have seen on the supplier's page. Mark “verified” only if you checked the live page.</p>
      <div className="form">
        <label>Supplier<input list="sup" value={f.supplier_id} onChange={(e) => setF({ ...f, supplier_id: e.target.value })} />
          <datalist id="sup">{suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</datalist></label>
        <label>Price (RON)<input type="number" step="0.01" value={f.price_ron} onChange={(e) => setF({ ...f, price_ron: e.target.value })} /></label>
        <label>Price includes VAT<select value={String(f.includes_vat)} onChange={(e) => setF({ ...f, includes_vat: e.target.value === "true" })}><option value="true">Yes</option><option value="false">No</option></select></label>
        <label>Status<select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="user_estimate">My estimate</option><option value="verified">Verified on supplier page</option></select></label>
        <label>Product URL<input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://…" /></label>
        <label>Availability<input value={f.availability} onChange={(e) => setF({ ...f, availability: e.target.value })} /></label>
      </div>
      <div className="row"><button className="primary" onClick={async () => {
        try { await api.post("/api/shopping/offers", { item_id: line.id, ...f, price_ron: Number(f.price_ron) }); setMsg("Added."); onDone(); }
        catch (e) { setMsg(String(e).replace(/^Error: \d+ /, "")); }
      }}>Add price</button><span className="muted">{msg}</span></div>
    </div>
  );
}

export default function ShoppingPage() {
  const [tier, setTier] = useState<string>("");
  const [optional, setOptional] = useState(true);
  const q = `?${tier ? `tier=${tier}&` : ""}include_optional=${optional}`;
  const [data, , reload] = usePoll<J>(`/api/shopping${q}`, 0);
  const [dir] = usePoll<J>("/api/shopping/suppliers", 0);
  const [open, setOpen] = useState<string | null>(null);
  if (!data || !dir) return <p className="muted">Loading…</p>;
  const b = data.budget;
  const bySub: Record<string, J[]> = {};
  data.lines.forEach((l: J) => (bySub[l.subsystem] ??= []).push(l));
  const bought = data.lines.filter((l: J) => l.purchased).length;

  return (
    <>
      <section className="card">
        <div className="card-head">
          <h2>Shopping list — {data.tier} configuration</h2>
          <div className="row">
            {["low", "recommended", "professional"].map((t) => (
              <button key={t} className={data.tier === t ? "pill on" : "pill"} onClick={() => setTier(t)}>{t}</button>))}
            <label className="inline"><input type="checkbox" checked={optional} onChange={(e) => setOptional(e.target.checked)} />optional items</label>
          </div>
        </div>
        <p className="muted">{data.label}</p>
        <div className="tiles">
          <div className="tile"><div className="tile-label">Total of priced lines</div><div className="tile-value">{ron(b.grand_total_ron)}<span className="unit">RON</span></div>
            <div className="tile-note">{ron(b.of_which_verified_ron)} verified · {ron(b.of_which_user_estimate_ron)} your estimates</div></div>
          <div className="tile warn"><div className="tile-label">Lines without price</div><div className="tile-value">{b.unpriced_lines} / {b.lines}</div></div>
          <div className="tile"><div className="tile-label">Quantities needing input</div><div className="tile-value">{b.needs_input_lines}</div><div className="tile-note">fill them on the Planner page</div></div>
          <div className="tile"><div className="tile-label">Purchased</div><div className="tile-value">{bought} / {data.lines.length}</div></div>
        </div>
        <div className="row">
          {["csv", "xlsx", "pdf"].map((f) => <a key={f} className="pill" href={`/api/shopping/export.${f}${q}`}>Export {f.toUpperCase()}</a>)}
        </div>
      </section>

      <section className="card">
        <h2>Budget by subsystem</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>Subsystem</th><th>Lines</th><th>Priced</th><th>Needs input</th><th>Priced total RON</th></tr></thead>
          <tbody>{Object.entries<J>(b.by_subsystem).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v.lines}</td><td>{v.priced_lines}</td><td>{v.needs_input_lines}</td><td>{ron(v.priced_total_ron)}</td></tr>)}</tbody>
        </table></div>
        <p className="muted">Priced totals by tier: {Object.entries<number>(data.tier_totals_ron).map(([t, v]) => `${t} ${ron(v)} RON`).join(" · ")} (priced lines only, so tiers are not comparable until prices are entered)</p>
      </section>

      {Object.entries(bySub).map(([sub, lines]) => (
        <section className="card" key={sub}>
          <h2>{sub}</h2>
          <div className="table-wrap"><table>
            <thead><tr><th>✓</th><th>Item</th><th>Qty</th><th>Unit RON</th><th>Total RON</th><th>Price status</th><th>Supplier</th><th /></tr></thead>
            <tbody>{lines.map((l) => {
              const best = l.offers.find((o: J) => o.id === l.best_offer_id);
              return (
                <Fragment key={l.id}>
                  <tr>
                    <td><input type="checkbox" checked={l.purchased} onChange={async (e) => { await api.put(`/api/shopping/purchased/${l.id}`, { purchased: e.target.checked }); reload(); }} /></td>
                    <td style={{ whiteSpace: "normal", minWidth: 260 }}><b>{l.name}</b> <span className="badge">{l.group}</span><br /><span className="muted">{l.spec}</span>
                      {l.compat && <><br /><span className="muted">⚙ {l.compat}</span></>}
                      {l.alternatives.length > 0 && <><br /><span className="muted">Alternatives: {l.alternatives.join("; ")}</span></>}</td>
                    <td>{l.qty ?? "?"}<br /><span className="muted" style={{ whiteSpace: "normal" }}>{l.qty === null ? `needs: ${l.qty_missing.join(", ")}` : l.qty_basis}</span></td>
                    <td>{ron(l.unit_price_ron)}</td><td>{ron(l.total_ron)}</td>
                    <td><span className={l.price_status === "verified" ? "badge ok" : "badge"}>{STATUS[l.price_status]}</span></td>
                    <td style={{ whiteSpace: "normal" }}>{best ? <>{dir.suppliers.find((s: J) => s.id === best.supplier_id)?.name ?? best.supplier_id}{best.url && <> · <a href={best.url} target="_blank" rel="noreferrer">product page</a></>}<br /><span className="muted">{best.availability} · checked {new Date(best.checked_at * 1000).toLocaleDateString()}</span></> : "–"}</td>
                    <td><button className="pill" onClick={() => setOpen(open === l.id ? null : l.id)}>Prices</button></td>
                  </tr>
                  {open === l.id && <tr><td colSpan={8}>
                    {l.offers.map((o: J) => (
                      <p key={o.id} className="muted">{o.supplier_id}: {ron(o.price_ron)} RON {o.includes_vat ? "incl." : "excl."} VAT ({STATUS[o.status]}) {o.url &&
                        <a href={o.url} target="_blank" rel="noreferrer">link</a>} {o.note} <button className="pill" onClick={async () => { await fetch(`/api/shopping/offers/${o.id}`, { method: "DELETE" }); reload(); }}>Delete</button></p>))}
                    <OfferForm line={l} suppliers={dir.suppliers} onDone={reload} /></td></tr>}
                </Fragment>);
            })}</tbody>
          </table></div>
        </section>
      ))}

      <section className="card">
        <h2>Supplier comparison</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>Supplier</th><th>Items with a price</th><th>Coverage</th><th>Total RON</th></tr></thead>
          <tbody>{data.supplier_comparison.map((s: J) => <tr key={s.supplier_id}><td>{s.supplier}</td><td>{s.items_covered}</td><td>{s.coverage_pct}%</td><td>{ron(s.total_ron)}</td></tr>)}</tbody>
        </table></div>
        <h3>Supplier directory</h3>
        <ul className="checks">{dir.suppliers.map((s: J) => <li key={s.id}><a href={s.url} target="_blank" rel="noreferrer">{s.name}</a> — {s.kind}. <span className="muted">{s.note} (noted {s.verified})</span></li>)}</ul>
        <p className="muted">Named in the brief but not verified, so no link: {dir.unverified_targets.join(", ")}. {dir.note}</p>
      </section>
    </>
  );
}
