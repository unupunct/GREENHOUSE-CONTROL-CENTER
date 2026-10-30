import { useEffect, useRef, useState } from "react";
import { api, usePoll, type Sensor } from "../api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type J = Record<string, any>;
const errText = (e: unknown) => String(e).replace(/^Error: \d+ /, "").replace(/^\{"detail":"?|"?\}$/g, "");
const ALWAYS = "structure";

const extent = (it: J) => it.rotation === 90
  ? { x: it.x + it.w / 2 - it.h / 2, y: it.y + it.h / 2 - it.w / 2, w: it.h, h: it.w }
  : { x: it.x, y: it.y, w: it.w, h: it.h };
const layerOf = (it: J, types: J) => it.layer ?? types[it.type]?.layer ?? "equipment";

function moistureColor(v: number | null | undefined, base: string): string {
  if (v == null) return base;
  const t = Math.max(0, Math.min(1, v / 60));  // 0-60 % moisture: tan -> blue (display only)
  const a = [176, 139, 92], b = [58, 130, 200];
  return `rgb(${a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(",")})`;
}

export default function DesignerPage() {
  const [doc, , reloadDoc] = usePoll<J>("/api/layout", 0);
  const [sensors] = usePoll<Sensor[]>("/api/sensors", 5000);
  const [items, setItems] = useState<J[] | null>(null);
  const [grid, setGrid] = useState(0.5);
  const [sel, setSel] = useState<string | null>(null);
  const [layers, setLayers] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState("");
  const [warn, setWarn] = useState<string[]>([]);
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<J | null>(null);

  useEffect(() => {
    if (doc && items === null) { setItems(doc.items); setGrid(doc.grid_m); setWarn(doc.warnings); setLayers(Object.fromEntries(doc.layers.map((l: J) => [l.id, true]))); }
  }, [doc, items]);
  if (!doc || !items) return <p className="muted">Loading…</p>;

  const types: J = doc.types, W = doc.draw_w_m, H = doc.draw_h_m;
  const snap = (v: number) => Math.round(v / grid) * grid;
  const r2 = (v: number) => Math.round(v * 100) / 100;
  const byId: Record<string, Sensor> = Object.fromEntries((sensors ?? []).map((s) => [s.id, s]));
  const selected = items.find((i) => i.id === sel) ?? null;
  const patch = (id: string, p: J) => setItems(items.map((i) => (i.id === id ? { ...i, ...p } : i)));

  const toM = (e: React.PointerEvent) => {
    const svg = svgRef.current!;
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    return { x: p.x, y: p.y };
  };
  const add = (type: string) => {
    const t = types[type]; let n = 1; while (items.some((i) => i.id === `${type}_${n}`)) n++;
    const it = { id: `${type}_${n}`, type, x: 1, y: 1, w: Math.min(t.w, W), h: Math.min(t.h, H), rotation: 0, label: "", link: null, layer: null };
    setItems([...items, it]); setSel(it.id);
  };
  const live = (it: J) => {
    if (it.link?.kind !== "sensor") return null;
    const s = byId[it.link.id];
    return s && s.value !== null ? `${s.value} ${s.unit}` : null;
  };

  const down = (e: React.PointerEvent, it: J) => {
    e.stopPropagation(); setSel(it.id);
    (e.target as Element).setPointerCapture(e.pointerId);
    const p = toM(e); drag.current = { mode: "move", id: it.id, dx: p.x - it.x, dy: p.y - it.y };
  };
  const downResize = (e: React.PointerEvent, it: J) => {
    e.stopPropagation(); (e.target as Element).setPointerCapture(e.pointerId); drag.current = { mode: "resize", id: it.id };
  };
  const move = (e: React.PointerEvent) => {
    const d = drag.current; if (!d) return;
    const p = toM(e), it = items.find((i) => i.id === d.id)!;
    if (d.mode === "move") patch(d.id, { x: r2(snap(p.x - d.dx)), y: r2(snap(p.y - d.dy)) });
    else patch(d.id, { w: Math.max(grid, r2(snap(p.x - it.x))), h: Math.max(grid, r2(snap(p.y - it.y))) });
  };
  const up = () => { drag.current = null; };

  const save = async () => {
    try { const r = await api.put<J>("/api/layout", { items, grid_m: grid }); setWarn(r.warnings); setMsg("Saved."); reloadDoc(); }
    catch (e) { setMsg(errText(e)); }
  };
  const svgString = () => {
    const clone = svgRef.current!.cloneNode(true) as SVGSVGElement;
    clone.querySelectorAll(".handle").forEach((n) => n.remove());
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    return new XMLSerializer().serializeToString(clone);
  };
  const download = (url: string, name: string) => { const a = document.createElement("a"); a.href = url; a.download = name; a.click(); };
  const exportSvg = () => download(URL.createObjectURL(new Blob([svgString()], { type: "image/svg+xml" })), "greenhouse-layout.svg");
  const exportPng = () => {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas"); c.width = 1600; c.height = Math.round(1600 * (H + 1) / (W + 1));
      const g = c.getContext("2d")!; g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(img, 0, 0, c.width, c.height);
      download(c.toDataURL("image/png"), "greenhouse-layout.png");
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svgString());
  };
  const shown = Object.entries(layers).filter(([, v]) => v).map(([k]) => k).join(",");
  const soilVal = (it: J) => (it.type === "bed_soil" && it.link?.kind === "sensor" ? byId[it.link.id]?.value : null);

  return (
    <>
      <section className="card">
        <div className="card-head"><h2>Greenhouse designer — {doc.length_m} × {doc.width_m} m ({W} × {H} m drawing)</h2>
          <div className="row">
            <label className="inline">grid<select value={grid} onChange={(e) => setGrid(Number(e.target.value))}>{[0.1, 0.25, 0.5, 1].map((g) => <option key={g} value={g}>{g} m</option>)}</select></label>
            <button className="primary" onClick={save}>Save layout</button>
            <button className="pill" onClick={() => { setItems(null); reloadDoc(); }}>Discard changes</button>
          </div></div>
        <div className="row">{doc.layers.map((l: J) => <label key={l.id} className="check"><input type="checkbox" checked={l.id === ALWAYS ? true : layers[l.id] ?? true} disabled={l.id === ALWAYS}
          onChange={(e) => setLayers({ ...layers, [l.id]: e.target.checked })} />{l.label}</label>)}</div>
        <div className="row" style={{ margin: "8px 0" }}>{Object.entries<J>(types).map(([k, t]) => <button key={k} className="pill" onClick={() => add(k)} title={`${t.layer} layer`}>+ {t.label}</button>)}</div>
        {warn.map((w) => <div key={w} className="banner warning">{w}</div>)}
        <div className="designer">
          <svg ref={svgRef} className="design-svg" viewBox={`-0.5 -0.5 ${W + 1} ${H + 1}`} onPointerMove={move} onPointerUp={up} onPointerDown={() => setSel(null)}>
            <defs><pattern id="gridp" width={grid} height={grid} patternUnits="userSpaceOnUse"><path d={`M ${grid} 0 L 0 0 0 ${grid}`} fill="none" stroke="#999" strokeWidth={0.01} opacity={0.35} /></pattern></defs>
            <rect x={0} y={0} width={W} height={H} fill="url(#gridp)" stroke="#222" strokeWidth={0.08} />
            <text x={0} y={-0.15} fontSize={0.35} fill="#555">{W} m</text>
            <text x={-0.15} y={H} fontSize={0.35} fill="#555" transform={`rotate(-90 -0.15 ${H})`}>{H} m</text>
            {items.filter((it) => { const l = layerOf(it, types); return l === ALWAYS || layers[l] !== false; }).map((it) => {
              const e = extent(it), t = types[it.type] ?? types.other, v = live(it), isSel = it.id === sel;
              const fill = layers.soil_moisture !== false && soilVal(it) != null ? moistureColor(soilVal(it), t.color) : t.color;
              const text = `${it.label || t.label}${v ? ` ${v}` : ""}`;
              return (
                <g key={it.id} onPointerDown={(ev) => down(ev, it)} style={{ cursor: "move" }}>
                  <rect x={e.x} y={e.y} width={e.w} height={e.h} fill={fill} stroke={isSel ? "#e11" : "#333"} strokeWidth={isSel ? 0.07 : 0.025} opacity={0.9} />
                  <text x={e.x + 0.05} y={e.y + Math.min(e.h / 2 + 0.12, e.h)} fontSize={Math.min(0.32, Math.max(0.18, e.h * 0.6))} fill="#111">{text}</text>
                  {isSel && it.rotation === 0 && <circle className="handle" cx={e.x + e.w} cy={e.y + e.h} r={0.15} fill="#e11" style={{ cursor: "nwse-resize" }} onPointerDown={(ev) => downResize(ev, it)} />}
                </g>);
            })}
          </svg>

          <div className="panel">
            {!selected ? <span className="muted">Click an item to edit it. Drag to move; drag the red dot to resize (unrotated items). Sensors show live readings; soil beds linked to a soil-moisture sensor are coloured by moisture.</span> : <>
              <b>{selected.id}</b>
              <label>Label<input value={selected.label} onChange={(e) => patch(selected.id, { label: e.target.value })} /></label>
              <div className="form" style={{ gridTemplateColumns: "1fr 1fr" }}>
                {(["x", "y", "w", "h"] as const).map((k) => <label key={k}>{k} (m)<input type="number" step={grid} value={selected[k]} onChange={(e) => patch(selected.id, { [k]: Number(e.target.value) })} /></label>)}
              </div>
              <label className="check"><input type="checkbox" checked={selected.rotation === 90} onChange={(e) => patch(selected.id, { rotation: e.target.checked ? 90 : 0 })} />Rotate 90°</label>
              <label>Link to<select value={selected.link?.kind ?? ""} onChange={(e) => patch(selected.id, { link: e.target.value ? { kind: e.target.value, id: selected.link?.id ?? "" } : null })}>
                <option value="">nothing</option>{["sensor", "actuator", "window", "zone", "tank"].map((k) => <option key={k}>{k}</option>)}</select></label>
              {selected.link && <label>Link ID<input list="linkids" value={selected.link.id} onChange={(e) => patch(selected.id, { link: { ...selected.link, id: e.target.value } })} />
                <datalist id="linkids">{selected.link.kind === "sensor" && (sensors ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</datalist></label>}
              <label>Layer<select value={selected.layer ?? ""} onChange={(e) => patch(selected.id, { layer: e.target.value || null })}>
                <option value="">default ({types[selected.type]?.layer})</option>{doc.layers.map((l: J) => <option key={l.id} value={l.id}>{l.label}</option>)}</select></label>
              <div className="row">
                <button className="pill" onClick={() => { let n = 1; while (items.some((i) => i.id === `${selected.type}_${n}`)) n++; const c = { ...selected, id: `${selected.type}_${n}`, x: r2(selected.x + 0.5), y: r2(selected.y + 0.5) }; setItems([...items, c]); setSel(c.id); }}>Duplicate</button>
                <button className="pill" onClick={() => { setItems(items.filter((i) => i.id !== selected.id)); setSel(null); }}>Delete</button></div></>}
          </div>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <a className="pill" href={`/api/layout/export.pdf?readings=true&layers=${shown}`}>Export PDF (with live readings)</a>
          <a className="pill" href={`/api/layout/export.pdf?layers=${shown}`}>PDF (plain)</a>
          <button className="pill" onClick={exportPng}>Export PNG</button><button className="pill" onClick={exportSvg}>Export SVG</button>
          <span className="muted">{msg} The PDF uses the saved layout. Positions are metres from the top-left corner; the long side is drawn horizontally.</span>
        </div>
      </section>
    </>
  );
}
