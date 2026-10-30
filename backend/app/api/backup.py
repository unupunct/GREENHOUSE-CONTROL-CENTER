from __future__ import annotations

import gzip
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.services import backup as bk
from app.services import events

router = APIRouter(prefix="/api/backup")


def _st(r: Request):
    return r.app.state


@router.get("")
def overview(request: Request):
    st = _st(request)
    last = bk.last_backup(st.settings)
    free = __import__("shutil").disk_usage(bk.backup_dir(st.settings)).free
    return {"settings": bk.load_settings(st.db).model_dump(), "backups": bk.list_backups(st.settings), "last": last,
            "free_gb": round(free / 1024**3, 1), "folder": str(bk.backup_dir(st.settings)),
            "warning": "Backups contain everything, including password hashes. Keep them private and copy them OFF the Raspberry Pi."}


@router.put("/settings")
def put_settings(body: bk.BackupSettings, request: Request):
    if body.copy_dir and not Path(body.copy_dir).is_dir():
        raise HTTPException(422, "the copy folder does not exist or is not a folder")
    bk.save_settings(_st(request).db, body)
    return body.model_dump()


@router.post("", status_code=201)
def make(request: Request):
    st = _st(request)
    try:
        man = bk.create(st.db, st.settings, "manual")
    except OSError as exc:
        raise HTTPException(507, str(exc)) from exc
    b = bk.load_settings(st.db)
    err = bk.copy_offsite(st.settings, b, man)
    bk.prune(st.settings, b.keep)
    events.log_event(st.db, "info", "backup", f"Manual backup {man['name']}")
    return {**man, "copy_error": err}


@router.post("/verify")
def verify(request: Request):
    """Automated test of backup and restore (also used by the commissioning checklist)."""
    st = _st(request)
    return bk.verify_roundtrip(st.db, st.settings)


@router.get("/{name}/download")
def download(name: str, request: Request, gz: bool = True):
    p = bk.path_of(_st(request).settings, name)
    if p is None:
        raise HTTPException(404, "backup not found")
    data = p.read_bytes()
    if gz:
        return Response(gzip.compress(data), media_type="application/gzip", headers={"Content-Disposition": f'attachment; filename="{name}.gz"'})
    return Response(data, media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.delete("/{name}")
def remove(name: str, request: Request):
    if not bk.delete(_st(request).settings, name):
        raise HTTPException(404, "backup not found")
    return {"ok": True}


class RestoreIn(BaseModel):
    confirm: bool = False


@router.post("/{name}/restore")
async def restore_named(name: str, body: RestoreIn, request: Request):
    if not body.confirm:
        raise HTTPException(422, "confirm: restoring replaces ALL current data (a pre-restore backup is made first)")
    p = bk.path_of(_st(request).settings, name)
    if p is None:
        raise HTTPException(404, "backup not found")
    try:
        return await bk.restore(request.app, p)
    except ValueError as exc:
        raise HTTPException(422, f"refused: {exc}") from exc


@router.post("/restore-upload")
async def restore_upload(request: Request, confirm: bool = False):
    """Body = the raw backup file (.db, or .db.gz). Nothing is replaced unless the file verifies."""
    if not confirm:
        raise HTTPException(422, "add ?confirm=true: restoring replaces ALL current data")
    raw = await request.body()
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError) as exc:
            raise HTTPException(422, f"refused: bad gzip data ({exc})") from exc
    with tempfile.TemporaryDirectory(dir=bk.backup_dir(_st(request).settings)) as tmp:
        p = Path(tmp) / "upload.db"
        p.write_bytes(raw)
        try:
            return await bk.restore(request.app, p)
        except ValueError as exc:
            raise HTTPException(422, f"refused: {exc}") from exc
