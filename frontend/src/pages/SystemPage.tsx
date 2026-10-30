import { usePoll, type EventRow } from "../api";

interface Sys {
  is_raspberry_pi: boolean; pi_model: string | null; os: string; machine: string; python: string;
  cpu_percent: number; cpu_temp_c: number | null; memory_percent: number;
  disk_free_gb: number; disk_total_gb: number; compatible: boolean;
  checks: { name: string; ok: boolean; detail: string }[];
  database_path: string; retention_days: number; flush_interval_s: number;
}
interface Safety {
  production_automation_allowed: boolean; reason: string; note: string;
  required_checks: { name: string; implemented: boolean; passed: boolean }[];
}

export default function SystemPage() {
  const [sys] = usePoll<Sys>("/api/system", 10000);
  const [safety] = usePoll<Safety>("/api/safety", 0);
  const [events] = usePoll<EventRow[]>("/api/events?limit=50", 10000);

  return (
    <>
      <section className="card">
        <h2>Platform</h2>
        {!sys ? <p className="muted">Loading…</p> : (
          <>
            <p>{sys.is_raspberry_pi ? `Raspberry Pi: ${sys.pi_model}` : "Not running on a Raspberry Pi (development host)."}
              {" "}<span className={sys.compatible ? "badge ok" : "badge"}>{sys.compatible ? "compatible" : "check failed"}</span></p>
            <ul className="checks">
              {sys.checks.map((c) => <li key={c.name}>{c.ok ? "✅" : "❌"} {c.name} <span className="muted">({c.detail})</span></li>)}
            </ul>
            <p className="muted">OS {sys.os} · CPU {sys.cpu_percent}%
              {sys.cpu_temp_c !== null && ` · ${sys.cpu_temp_c.toFixed(0)} °C`} · RAM {sys.memory_percent}% ·
              disk {sys.disk_free_gb}/{sys.disk_total_gb} GB free</p>
            <p className="muted">Database <code>{sys.database_path}</code> · samples written every {sys.flush_interval_s}s ·
              kept {sys.retention_days} days</p>
          </>
        )}
      </section>

      <section className="card">
        <h2>Commissioning gate</h2>
        {safety && (
          <>
            <p><span className="badge">Automation blocked</span> {safety.reason}</p>
            <ul className="checks">
              {safety.required_checks.map((c) => (
                <li key={c.name}>{c.passed ? "✅" : "⬜"} {c.name.replace(/_/g, " ")}
                  <span className="muted"> {c.implemented ? "" : "(test not implemented yet)"}</span></li>))}
            </ul>
            <p className="muted">{safety.note}</p>
          </>
        )}
      </section>

      <section className="card">
        <h2>Event log</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Time</th><th>Level</th><th>Source</th><th>Message</th></tr></thead>
            <tbody>{events?.map((e) => (
              <tr key={e.id}><td>{new Date(e.ts * 1000).toLocaleString()}</td><td>{e.level}</td>
                <td>{e.source}</td><td>{e.message}</td></tr>))}</tbody>
          </table>
        </div>
      </section>
    </>
  );
}
