from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Request, Response

from app.manual import content, render

router = APIRouter(prefix="/api/manual")


def _build(request: Request, kind: str, tier: str | None):
    d = content.collect(request.app, tier)
    secs = content.sections(d, kind)
    title = ("Installation checklist" if kind == "checklist" else "Installation manual") + f": {d['cfg'].name}"
    return d, secs, title


@router.get("/preview")
def preview(request: Request, kind: Literal["manual", "checklist"] = "manual", tier: Literal["low", "recommended", "professional"] | None = None):
    d, secs, title = _build(request, kind, tier)
    return {"title": title, "tier": d["tier"], "sections": [{"heading": h, "blocks": len(b)} for h, b in secs],
            "real_sensors": len(d["real_sensors"]), "real_outputs": len(d["real_acts"]),
            "simulated_sensors": len(d["sim_sensors"]), "simulated_outputs": len(d["sim_acts"]),
            "note": "Generated from the live configuration. Regenerate after changes." if d["real_sensors"] or d["real_acts"] else
                    "No real hardware is registered yet: the manual will say so instead of printing generic instructions."}


@router.get("/download.{fmt}")
def download(fmt: Literal["md", "html", "pdf"], request: Request, kind: Literal["manual", "checklist"] = "manual",
             tier: Literal["low", "recommended", "professional"] | None = None):
    d, secs, title = _build(request, kind, tier)
    stamp = time.strftime("%Y%m%d", time.localtime(d["generated_at"]))
    if fmt == "md":
        body, mime = render.markdown(title, secs, d).encode("utf-8"), "text/markdown; charset=utf-8"
    elif fmt == "html":
        body, mime = render.html_page(title, secs, d).encode("utf-8"), "text/html; charset=utf-8"
    else:
        body, mime = render.pdf(title, secs, d), "application/pdf"
    return Response(body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="greenhouse-{kind}-{stamp}.{fmt}"'})
