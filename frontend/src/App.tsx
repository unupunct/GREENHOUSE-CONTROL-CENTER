import { useEffect, useState } from "react";
import { usePoll, type Alert } from "./api";
import AdminPage from "./pages/AdminPage";
import { AccountPanel, LoginPage, SetupPage } from "./pages/AuthPages";
import Dashboard from "./pages/Dashboard";
import ConfigPage from "./pages/ConfigPage";
import SystemPage from "./pages/SystemPage";
import HardwarePage from "./pages/HardwarePage";
import EncyclopediaPage from "./pages/EncyclopediaPage";
import MaintenancePage from "./pages/MaintenancePage";
import ManualPage from "./pages/ManualPage";
import WizardPage from "./pages/WizardPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import DesignerPage from "./pages/DesignerPage";
import PlantsPage from "./pages/PlantsPage";
import ClimatePage from "./pages/ClimatePage";
import IrrigationPage from "./pages/IrrigationPage";
import PlannerPage from "./pages/PlannerPage";
import ShoppingPage from "./pages/ShoppingPage";
import WiringPage from "./pages/WiringPage";

type Mode = "basic" | "advanced";
type Theme = "light" | "dark";
type Page = "admin" | "dashboard" | "setup" | "maintenance" | "encyclopedia" | "manual" | "analytics" | "plants" | "designer" | "irrigation" | "climate" | "config" | "planner" | "shopping" | "wiring" | "hardware" | "system";

const PAGES: Page[] = ["admin", "dashboard", "setup", "maintenance", "encyclopedia", "manual", "analytics", "plants", "designer", "irrigation", "climate", "config", "planner", "shopping", "wiring", "hardware", "system"];

/** "#/climate" opens a page; "#/wiring?mode=advanced" also picks the interface mode (handy for bookmarks and screenshots). */
function fromHash(): { page: Page; mode: Mode | null } {
  const [p, q] = window.location.hash.replace(/^#\/?/, "").split("?");
  const m = new URLSearchParams(q ?? "").get("mode");
  return { page: (PAGES as string[]).includes(p) ? (p as Page) : "dashboard", mode: m === "advanced" || m === "basic" ? m : null };
}

function stored<T extends string>(key: string, fallback: T): T {
  try { return (localStorage.getItem(key) as T) || fallback; } catch { return fallback; }
}

function AppInner({ user, onAuth }: { user: { username: string; role: string }; onAuth: () => void }) {
  const [menu, setMenu] = useState(false);
  const [mode, setMode] = useState<Mode>(() => fromHash().mode ?? stored("gcc.mode", "basic"));
  const [theme, setTheme] = useState<Theme>(() => stored("gcc.theme", "light"));
  const [page, setPage] = useState<Page>(() => fromHash().page);
  useEffect(() => {
    const h = () => setPage(fromHash().page);
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  const [health] = usePoll<{ simulated: boolean; status: string; version: string }>("/api/health", 15000);
  const [alerts] = usePoll<Alert[]>("/api/alerts", 5000);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("gcc.theme", theme); localStorage.setItem("gcc.mode", mode); } catch { /* private mode */ }
  }, [theme, mode]);

  const advancedOnly: Page[] = ["system", "hardware", "wiring"];
  const isAdmin = user.role === "admin";
  const current: Page = advancedOnly.includes(page) && mode === "basic" ? "dashboard" : page;
  const tabs: [Page, string][] = [["dashboard", "Dashboard"], ["setup", "Setup guide"], ["irrigation", "Irrigation"], ["climate", "Climate"], ["plants", "Plants"], ["analytics", "Analytics"], ["designer", "Map"], ["config", "Greenhouse"], ["planner", "Planner"], ["shopping", "Shopping"], ["maintenance", "Maintenance"], ["encyclopedia", "Encyclopedia"], ["manual", "Manual"], ...(isAdmin ? ([["admin", "Admin"]] as [Page, string][]) : []),
    ...(mode === "advanced" ? ([["wiring", "Wiring"], ["hardware", "Hardware"], ["system", "System"]] as [Page, string][]) : [])];

  return (
    <div className="app">
      <header className="top">
        <div className="brand"><span className="leaf">🌿</span> Greenhouse Control Center</div>
        <nav>
          {tabs.map(([k, label]) => (
            <button key={k} className={current === k ? "tab active" : "tab"} onClick={() => { setPage(k); window.location.hash = `/${k}`; }}>{label}</button>
          ))}
        </nav>
        <div className="controls">
          <button className="pill" onClick={() => setMode(mode === "basic" ? "advanced" : "basic")}
            title="Basic: simple readings. Advanced: hardware and technical data.">
            {mode === "basic" ? "Basic mode" : "Advanced mode"}
          </button>
          <button className="pill" onClick={() => setMenu(!menu)} title="Account">👤 {user.username}</button>
          <button className="pill" onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            aria-label="Toggle theme">{theme === "light" ? "🌙" : "☀️"}</button>
        </div>
      </header>

      {menu && <AccountPanel user={user} onLogout={onAuth} />}
      {health?.simulated && (
        <div className="banner sim">Simulation mode: all values are generated, not measured. No hardware is connected.</div>
      )}
      {alerts?.map((a) => (
        <div key={a.id} className={`banner ${a.severity}`}>⚠ {a.message}
          {a.code !== "sensor_fault" && <button className="pill" style={{ marginLeft: 8 }} onClick={() => fetch(`/api/alerts/${a.id}/clear`, { method: "POST" })}>Clear</button>}</div>
      ))}

      <main>
        {current === "dashboard" && <Dashboard mode={mode} />}
        {current === "admin" && isAdmin && <AdminPage me={user.username} />}
        {current === "setup" && <WizardPage go={(p) => setPage(p as Page)} />}
        {current === "maintenance" && <MaintenancePage />}
        {current === "encyclopedia" && <EncyclopediaPage />}
        {current === "manual" && <ManualPage />}
        {current === "plants" && <PlantsPage />}
        {current === "analytics" && <AnalyticsPage />}
        {current === "designer" && <DesignerPage />}
        {current === "climate" && <ClimatePage mode={mode} />}
        {current === "irrigation" && <IrrigationPage mode={mode} />}
        {current === "config" && <ConfigPage mode={mode} />}
        {current === "planner" && <PlannerPage />}
        {current === "shopping" && <ShoppingPage />}
        {current === "wiring" && <WiringPage />}
        {current === "hardware" && <HardwarePage />}
        {current === "system" && <SystemPage />}
      </main>
      <footer>v{health?.version ?? "…"} · pre-release: software interlocks are tested, hardware control is not yet tested on real equipment</footer>
    </div>
  );
}

export default function App() {
  const [auth, , reload] = usePoll<{ auth_required: boolean; setup_needed: boolean; authenticated: boolean; user: { username: string; role: string } | null; password_min_length: number }>("/api/auth/status", 0);
  useEffect(() => {
    const h = () => reload();
    window.addEventListener("gcc-unauthorized", h);
    return () => window.removeEventListener("gcc-unauthorized", h);
  }, [reload]);
  if (!auth) return <p className="muted" style={{ padding: 24 }}>Loading…</p>;
  if (auth.setup_needed) return <SetupPage minLength={auth.password_min_length} onDone={reload} />;
  if (!auth.authenticated || !auth.user) return <LoginPage onDone={reload} />;
  return <AppInner key={auth.user.username} user={auth.user} onAuth={reload} />;
}
