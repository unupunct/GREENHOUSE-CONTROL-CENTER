import { useState } from "react";
import { api } from "../api";

const errText = (e: unknown) => String(e).replace(/^Error: \d+ /, "").replace(/^\{"detail":"?|"?\}$/g, "");

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="app" style={{ maxWidth: 440, paddingTop: 48 }}>
      <section className="card">
        <h2>🌿 Greenhouse Control Center</h2>
        <h3 style={{ marginTop: 0 }}>{title}</h3>
        {children}
      </section>
    </div>
  );
}

export function LoginPage({ onDone }: { onDone: () => void }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [msg, setMsg] = useState("");
  const submit = async () => {
    try { await api.post("/api/auth/login", { username: u, password: p }); onDone(); } catch (e) { setMsg(errText(e)); setP(""); }
  };
  return (
    <Shell title="Sign in">
      <form onSubmit={(e) => { e.preventDefault(); void submit(); }} className="form" style={{ gridTemplateColumns: "1fr" }}>
        <label>Username<input autoFocus autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} /></label>
        <label>Password<input type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} /></label>
        <button className="primary" type="submit" disabled={!u || !p}>Sign in</button>
      </form>
      {msg && <div className="banner critical">{msg}</div>}
      <p className="muted">Too many wrong passwords lock the account for a few minutes.</p>
    </Shell>
  );
}

export function SetupPage({ minLength, onDone }: { minLength: number; onDone: () => void }) {
  const [code, setCode] = useState("");
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [p2, setP2] = useState("");
  const [msg, setMsg] = useState("");
  const submit = async () => {
    if (p !== p2) { setMsg("The two passwords differ."); return; }
    try { await api.post("/api/auth/setup", { code, username: u, password: p }); onDone(); } catch (e) { setMsg(errText(e)); }
  };
  return (
    <Shell title="First start: create the administrator">
      <p className="muted">Nobody has an account yet. To prove you control this computer, enter the one-time setup code from the file <code>setup_code.txt</code> in the data folder
        (on the Raspberry Pi service: <code>sudo cat /var/lib/greenhouse/setup_code.txt</code>).</p>
      <form onSubmit={(e) => { e.preventDefault(); void submit(); }} className="form" style={{ gridTemplateColumns: "1fr" }}>
        <label>Setup code<input autoFocus value={code} onChange={(e) => setCode(e.target.value)} /></label>
        <label>Administrator username (3-48 letters, digits . _ -)<input autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} /></label>
        <label>Password (at least {minLength} characters)<input type="password" autoComplete="new-password" value={p} onChange={(e) => setP(e.target.value)} /></label>
        <label>Repeat password<input type="password" autoComplete="new-password" value={p2} onChange={(e) => setP2(e.target.value)} /></label>
        <button className="primary" type="submit" disabled={!code || !u || !p}>Create administrator</button>
      </form>
      {msg && <div className="banner critical">{msg}</div>}
    </Shell>
  );
}

export function AccountPanel({ user, onLogout }: { user: { username: string; role: string }; onLogout: () => void }) {
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [msg, setMsg] = useState("");
  return (
    <div className="panel" style={{ position: "absolute", right: 16, top: 56, zIndex: 5, background: "var(--surface)", minWidth: 280 }}>
      <b>{user.username}</b><span className="muted">role: {user.role}</span>
      <label>Current password<input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></label>
      <label>New password<input type="password" autoComplete="new-password" value={nw} onChange={(e) => setNw(e.target.value)} /></label>
      <div className="row">
        <button className="pill" disabled={!cur || !nw} onClick={async () => {
          try { const r = await api.post<{ other_sessions_ended: number }>("/api/auth/password", { current: cur, new: nw }); setMsg(`Changed. ${r.other_sessions_ended} other session(s) signed out.`); setCur(""); setNw(""); }
          catch (e) { setMsg(errText(e)); }
        }}>Change password</button>
        <button className="pill" onClick={async () => { await api.post("/api/auth/logout"); onLogout(); }}>Sign out</button>
      </div>
      <span className="muted">{msg}</span>
    </div>
  );
}
