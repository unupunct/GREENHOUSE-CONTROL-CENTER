import { useState } from "react";
import { api, usePoll } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
const errText = (e: unknown) => String(e).replace(/^Error: \d+ /, "").replace(/^\{"detail":"?|"?\}$/g, "");
const when = (t: number | null) => (t ? new Date(t * 1000).toLocaleString() : "–");

function Users({ me }: { me: string }) {
  const [users, , reload] = usePoll<J[]>("/api/users", 0);
  const [n, setN] = useState({ username: "", password: "", role: "viewer" });
  const [pw, setPw] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState("");
  const act = async (fn: () => Promise<unknown>) => { try { await fn(); setMsg("Done."); reload(); } catch (e) { setMsg(errText(e)); } };
  return (
    <section className="card">
      <h2>Users</h2>
      <p className="muted"><b>admin</b>: everything. <b>operator</b>: water, switch outputs, move windows, reset e-stop, acknowledge alerts, mark maintenance done. <b>viewer</b>: read only (and may press the emergency stop). Changing a user's role, password or status signs that user out.</p>
      <div className="table-wrap"><table>
        <thead><tr><th>User</th><th>Role</th><th>Active</th><th>Last sign-in</th><th>New password</th><th /></tr></thead>
        <tbody>{(users ?? []).map((u) => (
          <tr key={u.id}><td>{u.username}{u.username === me && " (you)"}</td>
            <td><select value={u.role} onChange={(e) => act(() => api.put(`/api/users/${u.id}`, { role: e.target.value }))}>{["admin", "operator", "viewer"].map((r) => <option key={r}>{r}</option>)}</select></td>
            <td><input type="checkbox" checked={!u.disabled} disabled={u.username === me} onChange={(e) => act(() => api.put(`/api/users/${u.id}`, { disabled: !e.target.checked }))} /></td>
            <td>{when(u.last_login_ts)}</td>
            <td className="row"><input type="password" autoComplete="new-password" value={pw[u.id] ?? ""} onChange={(e) => setPw({ ...pw, [u.id]: e.target.value })} />
              <button className="pill" disabled={!pw[u.id]} onClick={() => act(async () => { await api.put(`/api/users/${u.id}`, { password: pw[u.id] }); setPw({ ...pw, [u.id]: "" }); })}>Set</button></td>
            <td><button className="pill" disabled={u.username === me} onClick={() => confirm(`Delete ${u.username}?`) && act(async () => { const r = await fetch(`/api/users/${u.id}`, { method: "DELETE" }); if (!r.ok) throw new Error(await r.text()); })}>Delete</button></td></tr>))}</tbody>
      </table></div>
      <h3>Add a user</h3>
      <div className="form">
        <label>Username<input value={n.username} onChange={(e) => setN({ ...n, username: e.target.value })} /></label>
        <label>Password (min 10 characters)<input type="password" autoComplete="new-password" value={n.password} onChange={(e) => setN({ ...n, password: e.target.value })} /></label>
        <label>Role<select value={n.role} onChange={(e) => setN({ ...n, role: e.target.value })}>{["viewer", "operator", "admin"].map((r) => <option key={r}>{r}</option>)}</select></label>
      </div>
      <button className="primary" onClick={() => act(async () => { await api.post("/api/users", n); setN({ username: "", password: "", role: "viewer" }); })}>Add user</button> <span className="muted">{msg}</span>
    </section>
  );
}

function Backups() {
  const [d, , reload] = usePoll<J>("/api/backup", 0);
  const [msg, setMsg] = useState("");
  const [ver, setVer] = useState<J | null>(null);
  const [busy, setBusy] = useState(false);
  if (!d) return null;
  const s = d.settings;
  const save = (patch: J) => api.put("/api/backup/settings", { ...s, ...patch }).then(reload).catch((e) => setMsg(errText(e)));
  const restored = (r: J) => { setMsg(`Restored from ${r.restored_from}. The previous data was saved as ${r.pre_restore_backup}. Reloading…`); setTimeout(() => window.location.reload(), 1500); };
  return (
    <section className="card">
      <h2>Backup and restore</h2>
      <div className="banner warning">{d.warning} Folder: <code>{d.folder}</code> · {d.free_gb} GB free.</div>
      <div className="form">
        <label className="check"><input type="checkbox" checked={s.enabled} onChange={(e) => save({ enabled: e.target.checked })} />Daily automatic backup</label>
        <label>At (local time)<input type="time" value={s.time} onChange={(e) => save({ time: e.target.value })} /></label>
        <label>Keep the newest<input type="number" min={1} max={365} value={s.keep} onChange={(e) => save({ keep: Number(e.target.value) })} /></label>
        <label>Also copy to folder (USB / network share)<input defaultValue={s.copy_dir ?? ""} placeholder="/media/usb" onBlur={(e) => save({ copy_dir: e.target.value || null })} /></label>
      </div>
      <div className="row">
        <button className="primary" disabled={busy} onClick={async () => { setBusy(true); try { const r = await api.post<J>("/api/backup"); setMsg(`Backup ${r.name} written.${r.copy_error ? " Copy failed: " + r.copy_error : ""}`); reload(); } catch (e) { setMsg(errText(e)); } setBusy(false); }}>Back up now</button>
        <button className="pill" disabled={busy} onClick={async () => { setBusy(true); try { setVer(await api.post<J>("/api/backup/verify")); } catch (e) { setMsg(errText(e)); } setBusy(false); }}>Test backup and restore</button>
        <label className="pill" style={{ cursor: "pointer" }}>Restore from a file…
          <input type="file" accept=".db,.gz" style={{ display: "none" }} onChange={async (e) => {
            const f = e.target.files?.[0]; e.target.value = "";
            if (!f || !confirm(`Replace ALL current data with ${f.name}? A safety backup is made first.`)) return;
            try { const r = await fetch("/api/backup/restore-upload?confirm=true", { method: "POST", body: await f.arrayBuffer() }); if (!r.ok) throw new Error(await r.text()); restored(await r.json()); } catch (err) { setMsg(errText(err)); } }} /></label>
      </div>
      {ver && <div className={ver.ok ? "banner sim" : "banner critical"} style={{ marginTop: 8 }}>{ver.ok ? "✅ " : "❌ "}{ver.detail} ({ver.seconds}s)</div>}
      <div className="table-wrap" style={{ marginTop: 8 }}><table>
        <thead><tr><th>Backup</th><th>Kind</th><th>Created</th><th>Size</th><th>Sensors / measurements</th><th /></tr></thead>
        <tbody>{d.backups.map((b: J) => (
          <tr key={b.name}><td><code>{b.name}</code></td><td>{b.label}</td><td>{when(b.created_ts)}</td><td>{(b.size / 1024).toFixed(0)} KB</td><td>{b.rows.sensors} / {b.rows.measurements}</td>
            <td className="row"><a className="pill" href={`/api/backup/${b.name}/download`}>Download</a>
              <button className="pill" onClick={async () => { if (!confirm(`Restore ${b.name}? ALL current data is replaced (a safety backup is made first).`)) return;
                try { restored(await api.post<J>(`/api/backup/${b.name}/restore`, { confirm: true })); } catch (e) { setMsg(errText(e)); } }}>Restore</button>
              <button className="pill" onClick={async () => { await fetch(`/api/backup/${b.name}`, { method: "DELETE" }); reload(); }}>Delete</button></td></tr>))}</tbody>
      </table></div>
      {d.backups.length === 0 && <p className="muted">No backups yet.</p>}
      <p className="muted">{msg} Restoring switches every output off first and replaces users and sessions too: sign in again with an account that existed in the backup. Copy backups OFF the Raspberry Pi regularly.</p>
    </section>
  );
}

function Audit() {
  const [rows, , reload] = usePoll<J[]>("/api/audit?limit=200", 0);
  return (
    <section className="card">
      <div className="card-head"><h2>Audit log</h2><button className="pill" onClick={reload}>Refresh</button></div>
      <p className="muted">Sign-ins, failed sign-ins and every change request (never passwords or request contents).</p>
      <div className="table-wrap"><table>
        <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Result</th><th>From</th><th>Note</th></tr></thead>
        <tbody>{(rows ?? []).map((r) => <tr key={r.id}><td>{when(r.ts)}</td><td>{r.username || "–"} {r.role && <span className="muted">({r.role})</span>}</td><td><code>{r.method} {r.path}</code></td>
          <td><span className={r.status < 300 ? "chip" : "chip high"}>{r.status}</span></td><td>{r.ip}</td><td style={{ whiteSpace: "normal" }}>{r.detail}</td></tr>)}</tbody>
      </table></div>
    </section>
  );
}

export default function AdminPage({ me }: { me: string }) {
  return (<><Backups /><Users me={me} /><Audit /></>);
}
