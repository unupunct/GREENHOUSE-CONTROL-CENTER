"""Renderers: Markdown, HTML (with inline SVG diagram), PDF."""

from __future__ import annotations

import html as _html
import io
import json

from app.planner import wiring


# ------------------------------------------------------------ diagram
def diagram_model(d: dict) -> list[dict]:
    """Interfaces with the real devices behind them."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for x in d["real_sensors"]:
        a = json.loads(x.address or "{}")
        if x.driver == "modbus_rtu":
            k = f"RS485 bus {a.get('bus')}"
        elif x.driver == "sht3x":
            k = "I2C bus"
        elif x.driver == "ds18b20":
            k = "1-Wire (GPIO4)"
        elif x.driver == "gpio_input":
            k = "GPIO inputs"
        else:
            k = f"{x.driver}"
        groups.setdefault(k, []).append((x.id, "sensor"))
    for o in d["real_acts"]:
        a = json.loads(o.address or "{}")
        k = f"RS485 bus {a.get('bus')}" if o.driver == "modbus_coil" else "GPIO outputs (isolated drivers)" if o.driver == "gpio_output" else o.driver
        groups.setdefault(k, []).append((o.id, "output"))
    return [{"label": k, "devices": v} for k, v in groups.items()]


def svg(d: dict) -> str:
    g = diagram_model(d)
    if not g:
        return ""
    rowh, y, boxes = 22, 10, []
    for grp in g:
        shown = grp["devices"][:10]
        extra = len(grp["devices"]) - len(shown)
        n = len(shown) + (1 if extra else 0)
        boxes.append((grp, y, shown, extra))
        y += max(1, n) * rowh + 12
    H = y + 10
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 {H}" width="100%" role="img" font-family="sans-serif" font-size="11">',
           f'<rect x="10" y="{H / 2 - 30}" width="120" height="60" rx="6" fill="#2e8b57"/><text x="70" y="{H / 2 - 4}" fill="#fff" text-anchor="middle">Raspberry Pi</text>'
           f'<text x="70" y="{H / 2 + 12}" fill="#fff" text-anchor="middle">controller</text>']
    for grp, y0, shown, extra in boxes:
        n = len(shown) + (1 if extra else 0)
        cy = y0 + max(1, n) * rowh / 2
        out.append(f'<line x1="130" y1="{H / 2}" x2="230" y2="{cy}" stroke="#555"/>')
        out.append(f'<rect x="230" y="{cy - 14}" width="190" height="28" rx="5" fill="#e7f4ec" stroke="#2e8b57"/><text x="325" y="{cy + 4}" text-anchor="middle">{_html.escape(grp["label"])}</text>')
        for i, (name, kind) in enumerate(shown):
            yy = y0 + i * rowh + rowh / 2
            col = "#fdf3dc" if kind == "output" else "#eef3fb"
            out.append(f'<line x1="420" y1="{cy}" x2="470" y2="{yy}" stroke="#999"/><rect x="470" y="{yy - 9}" width="270" height="18" rx="3" fill="{col}" stroke="#888"/>'
                       f'<text x="478" y="{yy + 4}">{_html.escape(name)} <tspan fill="#777">({kind})</tspan></text>')
        if extra:
            yy = y0 + len(shown) * rowh + rowh / 2
            out.append(f'<text x="478" y="{yy + 4}" fill="#555">+ {extra} more</text>')
    out.append("</svg>")
    return "".join(out)


def drawing(d: dict):
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib import colors
    g = diagram_model(d)
    if not g:
        return None
    rowh, y, boxes = 16, 6, []
    for grp in g:
        shown = grp["devices"][:10]
        extra = len(grp["devices"]) - len(shown)
        n = len(shown) + (1 if extra else 0)
        boxes.append((grp, y, shown, extra))
        y += max(1, n) * rowh + 8
    H = y + 6
    dr = Drawing(520, H)

    def Y(v):  # SVG-style top-down -> reportlab bottom-up
        return H - v
    dr.add(Rect(4, Y(H / 2 + 22), 84, 44, fillColor=colors.HexColor("#2e8b57"), strokeColor=colors.HexColor("#2e8b57")))
    dr.add(String(46, Y(H / 2 + 2), "Raspberry Pi", fontSize=8, fillColor=colors.white, textAnchor="middle"))
    for grp, y0, shown, extra in boxes:
        n = len(shown) + (1 if extra else 0)
        cy = y0 + max(1, n) * rowh / 2
        dr.add(Line(88, Y(H / 2), 160, Y(cy), strokeColor=colors.grey))
        dr.add(Rect(160, Y(cy + 10), 140, 20, fillColor=colors.HexColor("#e7f4ec"), strokeColor=colors.HexColor("#2e8b57")))
        dr.add(String(230, Y(cy - 2), grp["label"].encode("latin-1", "replace").decode("latin-1")[:30], fontSize=7, textAnchor="middle"))
        for i, (name, kind) in enumerate(shown):
            yy = y0 + i * rowh + rowh / 2
            dr.add(Line(300, Y(cy), 330, Y(yy), strokeColor=colors.lightgrey))
            dr.add(Rect(330, Y(yy + 6), 186, 12, fillColor=colors.HexColor("#fdf3dc" if kind == "output" else "#eef3fb"), strokeColor=colors.grey))
            dr.add(String(334, Y(yy - 2), f"{name} ({kind})"[:44], fontSize=6.5))
        if extra:
            dr.add(String(334, Y(y0 + len(shown) * rowh + rowh / 2 - 2), f"+ {extra} more", fontSize=6.5))
    return dr


# ------------------------------------------------------------ markdown
def _md_cell(v) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def markdown(title: str, secs: list, d: dict) -> str:
    out = [f"# {title}", ""]
    for head, blocks in secs:
        out += [f"## {head}", ""]
        for b in blocks:
            k = b[0]
            if k == "p":
                out += [b[1], ""]
            elif k == "warn":
                out += [f"> **Warning:** {b[1]}", ""]
            elif k == "h3":
                out += [f"### {b[1]}", ""]
            elif k == "ul":
                out += [f"- {x}" for x in b[1]] + [""]
            elif k == "ol":
                out += [f"{i}. {x}" for i, x in enumerate(b[1], 1)] + [""]
            elif k == "code":
                out += ["```bash", b[1], "```", ""]
            elif k == "table":
                out += ["| " + " | ".join(b[1]) + " |", "|" + "---|" * len(b[1])] + ["| " + " | ".join(_md_cell(c) for c in r) + " |" for r in b[2]] + [""]
            elif k == "diagram":
                out += ["```mermaid", wiring.architecture(d["cfg"], d["opts"], d["sensors"]), "```", "", "*(Mermaid diagram: renders in viewers that support it; the Wiring page shows it too.)*", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- html
CSS = """body{font:14px/1.5 system-ui,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1d2a22}
h1{color:#1f6b41}h2{border-bottom:2px solid #2e8b57;padding-bottom:4px;margin-top:28px}table{border-collapse:collapse;width:100%;margin:8px 0;font-size:12px}
th,td{border:1px solid #bbb;padding:4px 6px;text-align:left;vertical-align:top}th{background:#e7f4ec}.warn{background:#fdf3dc;border-left:4px solid #b7791f;padding:8px 12px;margin:8px 0}
pre{background:#f3f3f3;padding:8px;overflow:auto}@media print{h2{page-break-after:avoid}table{page-break-inside:auto}tr{page-break-inside:avoid}body{margin:0}}"""


def html_page(title: str, secs: list, d: dict) -> str:
    e = _html.escape
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{e(title)}</title><style>{CSS}</style></head><body><h1>{e(title)}</h1>"]
    for head, blocks in secs:
        out.append(f"<h2>{e(head)}</h2>")
        for b in blocks:
            k = b[0]
            if k == "p":
                out.append(f"<p>{e(b[1])}</p>")
            elif k == "warn":
                out.append(f"<div class='warn'><b>Warning:</b> {e(b[1])}</div>")
            elif k == "h3":
                out.append(f"<h3>{e(b[1])}</h3>")
            elif k in ("ul", "ol"):
                out.append(f"<{k}>" + "".join(f"<li>{e(x)}</li>" for x in b[1]) + f"</{k}>")
            elif k == "code":
                out.append(f"<pre>{e(b[1])}</pre>")
            elif k == "table":
                out.append("<table><tr>" + "".join(f"<th>{e(h)}</th>" for h in b[1]) + "</tr>" +
                           "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in b[2]) + "</table>")
            elif k == "diagram":
                out.append(svg(d) or "<p>No real devices to draw.</p>")
    out.append("</body></html>")
    return "".join(out)


# ----------------------------------------------------------------- pdf
def _p(text) -> str:
    s = str(text).replace("≥", ">=").replace("≤", "<=").replace("→", "->").replace("₂", "2").replace("–", "-").replace("Ω", "ohm").replace("µ", "u")
    return s.encode("latin-1", "replace").decode("latin-1")


def pdf(title: str, secs: list, d: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    small = st["BodyText"].clone("small", fontSize=7, leading=8.5)
    warn = st["BodyText"].clone("warn", backColor=colors.HexColor("#fdf3dc"), borderPadding=4, spaceBefore=4, spaceAfter=6)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30, title=_p(title))
    story = [Paragraph(_p(title), st["Title"])]
    width = A4[0] - 60
    for head, blocks in secs:
        story.append(Paragraph(_p(head), st["Heading2"]))
        for b in blocks:
            k = b[0]
            if k == "p":
                story += [Paragraph(_p(b[1]), st["BodyText"]), Spacer(1, 4)]
            elif k == "warn":
                story.append(Paragraph("<b>Warning:</b> " + _p(b[1]).replace("&", "&amp;").replace("<", "&lt;"), warn))
            elif k == "h3":
                story.append(Paragraph(_p(b[1]), st["Heading3"]))
            elif k in ("ul", "ol"):
                story.append(ListFlowable([ListItem(Paragraph(_p(x).replace("&", "&amp;").replace("<", "&lt;"), st["BodyText"])) for x in b[1]],
                                          bulletType="bullet" if k == "ul" else "1"))
            elif k == "code":
                story.append(Preformatted(_p(b[1]), st["Code"]))
            elif k == "table":
                rows = [[Paragraph(f"<b>{_p(h)}</b>", small) for h in b[1]]] + [[Paragraph(_p(c).replace("&", "&amp;").replace("<", "&lt;"), small) for c in r] for r in b[2]]
                t = Table(rows, repeatRows=1, colWidths=[width / len(b[1])] * len(b[1]))
                t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7f4ec")), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                story += [t, Spacer(1, 6)]
            elif k == "diagram":
                dr = drawing(d)
                story.append(dr if dr is not None else Paragraph("No real devices to draw.", st["BodyText"]))
    doc.build(story)
    return buf.getvalue()
