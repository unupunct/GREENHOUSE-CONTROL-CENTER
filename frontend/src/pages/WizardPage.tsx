import { useState } from "react";
import { api, usePoll } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
const errText = (e: unknown) => String(e).replace(/^Error: \d+ /, "").replace(/^\{"detail":"?|"?\}$/g, "");
const LABEL: Record<string, string> = { done: "done", todo: "to do", in_progress: "in progress", blocked: "blocked", not_applicable: "not applicable" };

function Step({ s, go, reload, open, setOpen }: { s: J; go: (p: string) => void; reload: () => void; open: boolean; setOpen: () => void }) {
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const copy = (t: string) => { try { void navigator.clipboard.writeText(t); setMsg("Copied."); } catch { setMsg("Select and copy the text."); } };
  return (
    <section className="card">
      <div className="card-head" style={{ cursor: "pointer" }} onClick={setOpen}>
        <h2>{s.status === "done" ? "✅" : s.status === "not_applicable" ? "➖" : s.status === "blocked" ? "⛔" : "⬜"} {s.title} <span className="muted" style={{ fontWeight: 400 }}>· {s.stage}</span></h2>
        <span className={s.status === "done" ? "badge ok" : "badge"}>{LABEL[s.status]}</span>
      </div>
      <p>{s.detail}</p>
      {open && <>
        <p className="muted"><b>Why:</b> {s.why}</p>
        {s.how.length > 0 && <ul className="checks">{s.how.map((h: string) => <li key={h}>• {h}</li>)}</ul>}
        {s.questions.length > 0 && <div className="panel"><b>The application needs to know:</b>
          {s.questions.map((q: J) => <span key={q.label}><b>{q.label}:</b> {q.question} <span className="muted">(needed for {q.needed_for.join(", ")})</span></span>)}</div>}
        {s.commands.length > 0 && <div className="panel"><b>Commands (copy and run on the Raspberry Pi)</b>
          {s.commands.map((c: J) => <div key={c.cmd}><pre className="out" style={{ margin: "4px 0" }}>{c.cmd}</pre>
            <span className="muted">{c.explain} <button className="pill" onClick={() => copy(c.cmd)}>Copy</button></span></div>)}</div>}
        {s.link && <button className="pill" onClick={() => go(s.link)}>Open the page for this step</button>}
        {s.manual && <div className="row" style={{ marginTop: 8 }}>
          {s.attested ? <><span className="muted">Confirmed {new Date(s.attested.ts * 1000).toLocaleDateString()}: {s.attested.note}</span>
            <button className="pill" onClick={async () => { await fetch(`/api/wizard/${s.id}/confirm`, { method: "DELETE" }); reload(); }}>Undo</button></> :
            <><input style={{ flex: 1, minWidth: 220 }} placeholder="What did you do? (confirm by hand)" value={note} onChange={(e) => setNote(e.target.value)} />
              <button className="pill" onClick={async () => { try { await api.post(`/api/wizard/${s.id}/confirm`, { note }); setNote(""); reload(); } catch (e) { setMsg(errText(e)); } }}>I did this</button></>}
        </div>}
        <span className="muted">{msg}</span>
      </>}
    </section>
  );
}

export default function WizardPage({ go }: { go: (p: string) => void }) {
  const [w, , reload] = usePoll<J>("/api/wizard", 10000);
  const [open, setOpen] = useState<string | null>(null);
  if (!w) return <p className="muted">Loading…</p>;
  const cur = open ?? w.next;
  return (
    <>
      <section className="card">
        <h2>Setup guide</h2>
        <p>Progress: <b>{w.progress.done} of {w.progress.total}</b> steps ({w.progress.percent}%).{w.next && <> Next: <b>{w.steps.find((s: J) => s.id === w.next)?.title}</b>.</>}</p>
        <div style={{ background: "var(--border)", borderRadius: 999, height: 10 }}><div style={{ width: `${w.progress.percent}%`, background: "var(--green)", height: 10, borderRadius: 999 }} /></div>
        <p className="muted">Status comes from your real system (registered sensors, fresh readings, calibration, commissioning). Steps only a person can do are confirmed by hand. Mains work is for a qualified electrician.</p>
      </section>
      {w.steps.map((s: J) => <Step key={s.id} s={s} go={go} reload={reload} open={cur === s.id} setOpen={() => setOpen(cur === s.id ? "" : s.id)} />)}
    </>
  );
}
