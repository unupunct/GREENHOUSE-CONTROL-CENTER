import { useEffect, useState, type ReactNode } from "react";
import { api, usePoll, type Alert } from "./api";
import { Icon, Logo } from "./icons";
import { PAGE_DEFS, isPage, visibleGroups, type Page } from "./nav";
import AdminPage from "./pages/AdminPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import { AccountPanel, LoginPage, SetupPage } from "./pages/AuthPages";
import ClimatePage from "./pages/ClimatePage";
import ConfigPage from "./pages/ConfigPage";
import Dashboard from "./pages/Dashboard";
import DesignerPage from "./pages/DesignerPage";
import EncyclopediaPage from "./pages/EncyclopediaPage";
import HardwarePage from "./pages/HardwarePage";
import IrrigationPage from "./pages/IrrigationPage";
import MaintenancePage from "./pages/MaintenancePage";
import ManualPage from "./pages/ManualPage";
import PlannerPage from "./pages/PlannerPage";
import PlantsPage from "./pages/PlantsPage";
import ShoppingPage from "./pages/ShoppingPage";
import SystemPage from "./pages/SystemPage";
import WiringPage from "./pages/WiringPage";
import WizardPage from "./pages/WizardPage";

type Mode = "basic" | "advanced";
type Theme = "light" | "dark";
type User = { username: string; role: string };

/** "#/climate" opens a page; "#/wiring?mode=advanced&theme=light" also picks the interface mode and theme (handy for bookmarks and screenshots). */
function fromHash(): { page: Page; mode: Mode | null; theme: Theme | null } {
  const [p, q] = window.location.hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(q ?? "");
  const m = params.get("mode");
  const t = params.get("theme");
  return {
    page: isPage(p) ? p : "dashboard",
    mode: m === "advanced" || m === "basic" ? m : null,
    theme: t === "light" || t === "dark" ? t : null,
  };
}

function stored<T extends string>(key: string, fallback: T): T {
  try { return (localStorage.getItem(key) as T) || fallback; } catch { return fallback; }
}

const systemTheme = (): Theme => (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light");

function renderPage(page: Page, mode: Mode, user: User, go: (p: string) => void): ReactNode {
  const pages: Record<Page, () => ReactNode> = {
    dashboard: () => <Dashboard mode={mode} />,
    analytics: () => <AnalyticsPage />,
    designer: () => <DesignerPage />,
    irrigation: () => <IrrigationPage mode={mode} />,
    climate: () => <ClimatePage mode={mode} />,
    plants: () => <PlantsPage />,
    config: () => <ConfigPage mode={mode} />,
    setup: () => <WizardPage go={go} />,
    planner: () => <PlannerPage />,
    shopping: () => <ShoppingPage />,
    wiring: () => <WiringPage />,
    hardware: () => <HardwarePage />,
    maintenance: () => <MaintenancePage />,
    encyclopedia: () => <EncyclopediaPage />,
    manual: () => <ManualPage />,
    admin: () => <AdminPage me={user.username} />,
    system: () => <SystemPage />,
  };
  return pages[page]();
}

function AlertBanner({ a }: { a: Alert }) {
  return (
    <div className={`banner ${a.severity}`} role="alert">
      <Icon name="alert" size={16} />
      <span className="grow">{a.message}</span>
      {a.code !== "sensor_fault" && (
        <button className="pill small" onClick={() => void api.post(`/api/alerts/${a.id}/clear`).catch(() => undefined)}>Clear</button>
      )}
    </div>
  );
}

function AppInner({ user, onAuth }: { user: User; onAuth: () => void }) {
  const [account, setAccount] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [mode, setMode] = useState<Mode>(() => fromHash().mode ?? stored("gcc.mode", "basic"));
  const [theme, setTheme] = useState<Theme>(() => fromHash().theme ?? stored("gcc.theme", systemTheme()));
  const [page, setPage] = useState<Page>(() => fromHash().page);
  const [health] = usePoll<{ simulated: boolean; status: string; version: string }>("/api/health", 15000);
  const [alerts] = usePoll<Alert[]>("/api/alerts", 5000);

  useEffect(() => {
    const onHash = () => setPage(fromHash().page);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("gcc.theme", theme); localStorage.setItem("gcc.mode", mode); } catch { /* private mode */ }
  }, [theme, mode]);

  const isAdmin = user.role === "admin";
  const groups = visibleGroups(mode, isAdmin);
  const allowed = groups.some(([, pages]) => pages.some((p) => p.id === page));
  const current: Page = allowed ? page : "dashboard";
  const title = PAGE_DEFS.find((p) => p.id === current)?.label ?? "";
  const critical = alerts?.filter((a) => a.severity === "critical").length ?? 0;

  const go = (target: string) => {
    if (!isPage(target)) return;
    setPage(target);
    setDrawer(false);
    window.location.hash = `/${target}`;
  };

  return (
    <div className={`shell ${drawer ? "drawer-open" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand"><Logo /><span>Greenhouse<br />Control Center</span></div>
        <nav>
          {groups.map(([group, pages]) => (
            <div className="nav-group" key={group}>
              <div className="nav-title">{group}</div>
              {pages.map((p) => (
                <button key={p.id} className={current === p.id ? "nav-item active" : "nav-item"}
                  aria-current={current === p.id ? "page" : undefined} onClick={() => go(p.id)}>
                  <Icon name={p.icon} /><span>{p.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">v{health?.version ?? "…"} · pre-release</div>
      </aside>
      {drawer && <div className="scrim" onClick={() => setDrawer(false)} />}

      <div className="main-col">
        <header className="topbar">
          <button className="icon-btn menu-btn" aria-label="Open navigation" onClick={() => setDrawer(true)}><Icon name="menu" /></button>
          <h1>{title}</h1>
          <span className={`status ${critical ? "crit" : alerts?.length ? "warn" : "ok"}`}>
            <i />{critical ? `${critical} critical` : alerts?.length ? `${alerts.length} alert${alerts.length > 1 ? "s" : ""}` : "All normal"}
          </span>
          <span className="grow" />
          <div className="segmented" role="group" aria-label="Interface mode"
            title="Basic: simple readings. Advanced: hardware and technical data.">
            {(["basic", "advanced"] as const).map((m) => (
              <button key={m} className={mode === m ? "on" : ""} aria-pressed={mode === m} onClick={() => setMode(m)}>
                {m === "basic" ? "Basic" : "Advanced"}
              </button>
            ))}
          </div>
          <button className="icon-btn" aria-label="Toggle theme" title="Toggle light/dark"
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}><Icon name={theme === "light" ? "moon" : "sun"} /></button>
          <button className="pill account" onClick={() => setAccount(!account)} title="Account"><Icon name="user" size={16} /> {user.username}</button>
        </header>

        <div className="content">
          {account && <AccountPanel user={user} onLogout={onAuth} />}
          {health?.simulated && (
            <div className="banner sim"><Icon name="alert" size={16} />Simulation mode: all values are generated, not measured. No hardware is connected.</div>
          )}
          {alerts?.map((a) => <AlertBanner key={a.id} a={a} />)}
          <main>{renderPage(current, mode, user, go)}</main>
          <footer>Pre-release: software interlocks are tested, hardware control is not yet tested on real equipment.</footer>
        </div>
      </div>
    </div>
  );
}

type AuthStatus = {
  auth_required: boolean; setup_needed: boolean; authenticated: boolean;
  user: User | null; password_min_length: number;
};

export default function App() {
  const [auth, , reload] = usePoll<AuthStatus>("/api/auth/status", 0);
  useEffect(() => {
    window.addEventListener("gcc-unauthorized", reload);
    return () => window.removeEventListener("gcc-unauthorized", reload);
  }, [reload]);
  if (!auth) return <p className="muted loading">Loading…</p>;
  if (auth.setup_needed) return <SetupPage minLength={auth.password_min_length} onDone={reload} />;
  if (!auth.authenticated || !auth.user) return <LoginPage onDone={reload} />;
  return <AppInner key={auth.user.username} user={auth.user} onAuth={reload} />;
}
