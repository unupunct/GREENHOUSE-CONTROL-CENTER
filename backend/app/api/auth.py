from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.models import AuditLog, User
from app.security import client_ip
from app.services import auth

router = APIRouter(prefix="/api")


def _db(r: Request):
    return r.app.state.db


def _cookie(request: Request, response: Response, token: str | None) -> None:
    s = request.app.state.settings
    secure = s.cookie_secure if s.cookie_secure is not None else request.url.scheme == "https"
    if token is None:
        response.delete_cookie(auth.COOKIE, path="/")
    else:
        response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict", secure=secure, path="/", max_age=int(s.session_max_days * 86400))


def _user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "disabled": u.disabled, "created_at": u.created_at, "last_login_ts": u.last_login_ts}


@router.get("/auth/status")
def status(request: Request):
    st = request.app.state
    p = getattr(request.state, "principal", None)
    required = st.settings.auth_required
    return {"auth_required": required, "setup_needed": required and auth.count_users(st.db) == 0,
            "authenticated": (p is not None) or not required, "user": {"username": p.username, "role": p.role} if p else
            ({"username": "auth disabled", "role": "admin"} if not required else None),
            "password_min_length": auth.MIN_PASSWORD}


class SetupIn(BaseModel):
    code: str
    username: str
    password: str


@router.post("/auth/setup")
def setup(body: SetupIn, request: Request, response: Response):
    st = request.app.state
    if not st.settings.auth_required:
        raise HTTPException(409, "authentication is disabled")
    if auth.count_users(st.db) > 0:
        raise HTTPException(409, "already set up")
    ip = client_ip(request)
    wait = st.limiter.blocked(ip, "__setup__")
    if wait:
        raise HTTPException(429, f"too many attempts; wait {wait:.0f}s")
    if not auth.consume_setup_code(st.settings.data_dir, body.code):
        st.limiter.fail(ip, "__setup__")
        raise HTTPException(403, "wrong setup code (see setup_code.txt in the data folder)")
    try:
        uid = auth.create_user(st.db, body.username, body.password, "admin")
    except ValueError as exc:
        auth.ensure_setup_code(st.settings.data_dir)  # code was consumed: issue a new one so the user can retry
        raise HTTPException(422, str(exc)) from exc
    token = auth.create_session(st.db, uid, ip, request.headers.get("user-agent", ""))
    _cookie(request, response, token)
    auth.audit(st.db, None, ip, "POST", "/api/auth/setup", 200, f"first administrator '{body.username.lower()}' created")
    return {"ok": True, "username": body.username.lower(), "role": "admin"}


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=300)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response):
    st = request.app.state
    ip, uname = client_ip(request), body.username.strip().lower()
    wait = st.limiter.blocked(ip, uname)
    if wait:
        auth.audit(st.db, None, ip, "POST", "/api/auth/login", 429, f"locked: {uname}")
        raise HTTPException(429, f"too many failed attempts; try again in {wait:.0f}s")
    u = auth.authenticate(st.db, uname, body.password)
    if u is None:
        st.limiter.fail(ip, uname)
        auth.audit(st.db, None, ip, "POST", "/api/auth/login", 401, f"failed login: {uname}")
        raise HTTPException(401, "wrong username or password")
    st.limiter.ok(ip, uname)
    token = auth.create_session(st.db, u.id, ip, request.headers.get("user-agent", ""))
    _cookie(request, response, token)
    auth.audit(st.db, auth.Principal(u.id, u.username, u.role, ""), ip, "POST", "/api/auth/login", 200, "login")
    return {"username": u.username, "role": u.role}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    auth.revoke(_db(request), token=request.cookies.get(auth.COOKIE))
    _cookie(request, response, None)
    return {"ok": True}


class PasswordIn(BaseModel):
    current: str
    new: str


@router.post("/auth/password")
def change_password(body: PasswordIn, request: Request):
    p = request.state.principal
    if p is None:
        raise HTTPException(409, "authentication is disabled")
    st = request.app.state
    ip = client_ip(request)
    wait = st.limiter.blocked(ip, p.username)
    if wait:
        raise HTTPException(429, f"too many attempts; wait {wait:.0f}s")
    if auth.authenticate(st.db, p.username, body.current) is None:
        st.limiter.fail(ip, p.username)
        raise HTTPException(403, "current password is wrong")
    problem = auth.password_problem(body.new, p.username)
    if problem:
        raise HTTPException(422, problem)
    with st.db.session() as s:
        s.get(User, p.user_id).password_hash = auth.hash_password(body.new)
    n = auth.revoke(st.db, user_id=p.user_id, keep=p.session_id)
    auth.audit(st.db, p, ip, "POST", "/api/auth/password", 200, f"password changed; {n} other session(s) ended")
    return {"ok": True, "other_sessions_ended": n}


# ------------------------------------------------------------------- users (admin)
class UserIn(BaseModel):
    username: str
    password: str
    role: str = "viewer"


@router.get("/users")
def list_users(request: Request):
    with _db(request).session() as s:
        return [_user_dict(u) for u in s.scalars(select(User).order_by(User.username))]


@router.post("/users", status_code=201)
def add_user(body: UserIn, request: Request):
    try:
        uid = auth.create_user(_db(request), body.username, body.password, body.role)
    except ValueError as exc:
        raise HTTPException(409 if "exists" in str(exc) else 422, str(exc)) from exc
    return {"id": uid}


class UserPatch(BaseModel):
    role: str | None = None
    disabled: bool | None = None
    password: str | None = None


@router.put("/users/{uid}")
def edit_user(uid: int, body: UserPatch, request: Request):
    db = _db(request)
    me = request.state.principal
    with db.session() as s:
        u = s.get(User, uid)
        if u is None:
            raise HTTPException(404, "user not found")
        losing_admin = u.role == "admin" and ((body.role and body.role != "admin") or body.disabled)
        if body.role is not None and body.role not in auth.ROLES:
            raise HTTPException(422, "role must be admin, operator or viewer")
        if losing_admin and auth.admin_count(db, excluding=uid) == 0:
            raise HTTPException(409, "there must always be at least one active administrator")
        if me and me.user_id == uid and body.disabled:
            raise HTTPException(409, "you cannot disable your own account")
        if body.role is not None:
            u.role = body.role
        if body.disabled is not None:
            u.disabled = body.disabled
        if body.password is not None:
            problem = auth.password_problem(body.password, u.username)
            if problem:
                raise HTTPException(422, problem)
            u.password_hash = auth.hash_password(body.password)
    if body.password is not None or body.disabled or (body.role is not None):
        auth.revoke(db, user_id=uid, keep=me.session_id if me and me.user_id == uid else None)
    return {"ok": True}


@router.delete("/users/{uid}")
def delete_user(uid: int, request: Request):
    db = _db(request)
    me = request.state.principal
    with db.session() as s:
        u = s.get(User, uid)
        if u is None:
            raise HTTPException(404, "user not found")
        if me and me.user_id == uid:
            raise HTTPException(409, "you cannot delete your own account")
        if u.role == "admin" and auth.admin_count(db, excluding=uid) == 0:
            raise HTTPException(409, "there must always be at least one active administrator")
        s.delete(u)
    auth.revoke(db, user_id=uid)
    return {"ok": True}


@router.get("/audit")
def audit_log(request: Request, limit: int = 200):
    with _db(request).session() as s:
        rows = s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 1000)))).all()
    return [{"id": r.id, "ts": r.ts, "username": r.username, "role": r.role, "ip": r.ip, "method": r.method, "path": r.path,
             "status": r.status, "detail": r.detail} for r in rows]

