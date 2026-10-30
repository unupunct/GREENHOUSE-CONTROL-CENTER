import { useState } from "react";
import type { Point } from "./api";

interface Props { points: Point[]; unit: string; height?: number; band?: { min: number; max: number } | null }

const W = 640, PAD = { l: 44, r: 12, t: 10, b: 24 };

export default function LineChart({ points, unit, height = 200, band }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) {
    return <div className="chart-empty">Not enough history yet. Samples are stored once a minute.</div>;
  }
  const xs = points.map((p) => p.ts), ys = points.map((p) => p.value);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (band) { y0 = Math.min(y0, band.min); y1 = Math.max(y1, band.max); }
  if (y1 - y0 < 1e-6) { y0 -= 1; y1 += 1; }
  const padY = (y1 - y0) * 0.1; y0 -= padY; y1 += padY;
  const sx = (t: number) => PAD.l + ((t - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
  const sy = (v: number) => PAD.t + (1 - (v - y0) / (y1 - y0)) * (height - PAD.t - PAD.b);
  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(p.ts).toFixed(1)},${sy(p.value).toFixed(1)}`).join("");
  const ticks = [0, 0.5, 1].map((f) => y0 + f * (y1 - y0));
  const dec = y1 - y0 < 0.2 ? 3 : y1 - y0 < 2 ? 2 : y1 - y0 < 20 ? 1 : 0;
  const fmtT = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const h = hover !== null ? points[hover] : null;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="chart" role="img"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const t = x0 + (((e.clientX - r.left) / r.width) * W - PAD.l) / (W - PAD.l - PAD.r) * (x1 - x0);
        let best = 0;
        points.forEach((p, i) => { if (Math.abs(p.ts - t) < Math.abs(points[best].ts - t)) best = i; });
        setHover(best);
      }}>
      {ticks.map((v, i) => (
        <g key={i}>
          <line x1={PAD.l} x2={W - PAD.r} y1={sy(v)} y2={sy(v)} className="grid" />
          <text x={PAD.l - 6} y={sy(v) + 4} textAnchor="end" className="axis">{v.toFixed(dec)}</text>
        </g>
      ))}
      <text x={PAD.l} y={height - 6} className="axis">{fmtT(x0)}</text>
      <text x={W - PAD.r} y={height - 6} textAnchor="end" className="axis">{fmtT(x1)}</text>
      {band && <rect x={PAD.l} width={W - PAD.l - PAD.r} y={sy(band.max)} height={Math.max(0, sy(band.min) - sy(band.max))} className="band" />}
      <path d={d} className="line" />
      {h && (
        <g>
          <line x1={sx(h.ts)} x2={sx(h.ts)} y1={PAD.t} y2={height - PAD.b} className="cursor" />
          <circle cx={sx(h.ts)} cy={sy(h.value)} r={4} className="dot" />
          <text x={Math.min(sx(h.ts) + 8, W - 130)} y={PAD.t + 12} className="tip">
            {h.value.toFixed(2)} {unit} · {fmtT(h.ts)}
          </text>
        </g>
      )}
    </svg>
  );
}
