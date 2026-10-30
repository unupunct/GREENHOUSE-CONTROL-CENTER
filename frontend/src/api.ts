import { useCallback, useEffect, useState } from "react";

export interface Sensor {
  id: string; name: string; kind: string; zone: string; unit: string;
  driver: string; protocol: string; simulated: boolean; enabled: boolean;
  value: number | null; ts: number | null; status: "ok" | "stale" | "no_data" | "disabled";
}
export interface Vpd {
  available: boolean; temperature_c?: number; humidity_percent?: number;
  vpd_kpa?: number; dew_point_c?: number; assumption?: string;
}
export interface Config {
  name: string; country: string; currency: string; language: "en" | "ro";
  length_m: number; width_m: number; growing_methods: string[];
  automation_level: string; controller: string; os: string;
  height_m: number | null; ridge_height_m: number | null; orientation: string | null;
  construction: string | null; heating_required: boolean | null;
  water_pressure_bar: number | null; electricity_supply: string | null;
  latitude: number | null; longitude: number | null;
  area_m2: number; volume_m3: number | null;
}
export interface EngInput {
  key: string; label: string; question: string; needed_for: string[];
  provided: boolean; value: string | number | boolean | null;
}
export interface Alert {
  id: number; ts: number; severity: string; code: string; subject: string;
  message: string; active: boolean; acknowledged: boolean;
}
export interface EventRow { id: number; ts: number; level: string; source: string; message: string }
export interface Point { ts: number; value: number }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  get: <T,>(p: string) => req<T>(p),
  put: <T,>(p: string, body: unknown) => req<T>(p, { method: "PUT", body: JSON.stringify(body) }),
  post: <T,>(p: string, body?: unknown) =>
    req<T>(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
};

/** Fetch `path` now and every `everyMs`; returns [data, error, reload]. */
export function usePoll<T>(path: string, everyMs = 5000): [T | null, string | null, () => void] {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    api.get<T>(path).then((d) => { setData(d); setErr(null); }).catch((e) => setErr(String(e)));
  }, [path]);
  useEffect(() => {
    load();
    if (!everyMs) return;
    const t = setInterval(load, everyMs);
    return () => clearInterval(t);
  }, [load, everyMs]);
  return [data, err, load];
}
