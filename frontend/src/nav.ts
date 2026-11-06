import type { IconName } from "./icons";

/** Every page, in sidebar order. `advanced` pages show only in Advanced mode, `admin` pages only for administrators. */
export const PAGE_DEFS = [
  { id: "dashboard", label: "Dashboard", icon: "dashboard", group: "Monitor" },
  { id: "analytics", label: "Analytics", icon: "analytics", group: "Monitor" },
  { id: "designer", label: "Map", icon: "map", group: "Monitor" },
  { id: "irrigation", label: "Irrigation", icon: "droplet", group: "Control" },
  { id: "climate", label: "Climate", icon: "thermometer", group: "Control" },
  { id: "plants", label: "Plants", icon: "sprout", group: "Grow" },
  { id: "config", label: "Greenhouse", icon: "sliders", group: "Grow" },
  { id: "setup", label: "Setup guide", icon: "checklist", group: "Plan and build" },
  { id: "planner", label: "Planner", icon: "clipboard", group: "Plan and build" },
  { id: "shopping", label: "Shopping", icon: "cart", group: "Plan and build" },
  { id: "wiring", label: "Wiring", icon: "zap", group: "Plan and build", advanced: true },
  { id: "hardware", label: "Hardware", icon: "cpu", group: "Plan and build", advanced: true },
  { id: "maintenance", label: "Maintenance", icon: "wrench", group: "Learn and maintain" },
  { id: "encyclopedia", label: "Encyclopedia", icon: "book", group: "Learn and maintain" },
  { id: "manual", label: "Manual", icon: "file", group: "Learn and maintain" },
  { id: "admin", label: "Admin", icon: "shield", group: "System", admin: true },
  { id: "system", label: "System", icon: "server", group: "System", advanced: true },
] as const satisfies readonly { id: string; label: string; icon: IconName; group: string; advanced?: boolean; admin?: boolean }[];

export type Page = (typeof PAGE_DEFS)[number]["id"];
export type PageDef = { id: Page; label: string; icon: IconName; group: string; advanced?: boolean; admin?: boolean };

const IDS: string[] = PAGE_DEFS.map((p) => p.id);
export const isPage = (s: string): s is Page => IDS.includes(s);

/** The pages this user may open in this mode, grouped for the sidebar. */
export function visibleGroups(mode: "basic" | "advanced", isAdmin: boolean): [string, PageDef[]][] {
  const groups = new Map<string, PageDef[]>();
  for (const p of PAGE_DEFS as readonly PageDef[]) {
    if ((p.advanced && mode === "basic") || (p.admin && !isAdmin)) continue;
    groups.set(p.group, [...(groups.get(p.group) ?? []), p]);
  }
  return [...groups];
}
