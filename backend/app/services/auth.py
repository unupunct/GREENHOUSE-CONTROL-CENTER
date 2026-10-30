"""Local authentication: users, scrypt password hashes, server-side sessions, roles, rate limiting.

No secrets are stored in the clear: passwords as salted scrypt hashes, session
tokens only as SHA-256. Sessions are cookies (HttpOnly, SameSite=Strict).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select

from app.core.db import Database
from app.core.models import AuditLog, AuthSession, User

COOKIE = "gcc_session"
ROLES = {"viewer": 1, "operator": 2, "admin": 3}
MIN_PASSWORD = 10
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,48}$")
_N, _R, _P = 2**14, 8, 1


# --------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, h = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(h) // 2)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:  # noqa: BLE001
        return False


_DUMMY = hash_password(secrets.token_hex(8))  # compared against when the user does not exist (equal timing)


def password_problem(password: str, username: str = "") -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"password must be at least {MIN_PASSWORD} characters"
    if len(password) > 200:
        return "password is too long"
    if username and username.lower() in password.lower():
        return "password must not contain the username"
    if len(set(password)) < 4:
        return "password is too repetitive"
    return None


# -------------------------------------------------------------- rate limit
class RateLimiter:
    """Failed-login limiter per client address and per username (memory only)."""

    def __init__(self, per_ip: int = 10, per_user: int = 5, window_s: float = 600, lock_s: float = 300) -> None:
        self.per_ip, self.per_user, self.window, self.lock = per_ip, per_user, window_s, lock_s
        self._fails: dict[tuple[str, str], deque] = defaultdict(deque)

    def _prune(self, key, now):
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, ip: str, username: str, now: float | None = None) -> float:
        """Seconds to wait, 0 if allowed."""
        now = time.time() if now is None else now
        wait = 0.0
        for key, limit in ((("ip", ip), self.per_ip), (("user", username), self.per_user)):
            q = self._prune(key, now)
            if len(q) >= limit:
                wait = max(wait, self.lock - (now - q[-1]))
        return max(0.0, wait)

    def fail(self, ip: str, username: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if len(self._fails) > 5000:  # an attacker trying endless random usernames must not grow memory without bound
            for key in list(self._fails):
                if not self._prune(key, now):
                    del self._fails[key]
            if len(self._fails) > 5000:
                self._fails.clear()
        self._fails[("ip", ip)].append(now)
        self._fails[("user", username)].append(now)

    def ok(self, ip: str, username: str) -> None:
        self._fails.pop(("user", username), None)


# ------------------------------------------------------------------ sessions
@dataclass
class Principal:
    user_id: int
    username: str
    role: str
    session_id: str


def _tok_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Database, user_id: int, ip: str, agent: str, now: float | None = None) -> str:
    now = int(time.time() if now is None else now)
    token = secrets.token_urlsafe(32)
    with db.session() as s:
        s.add(AuthSession(id=_tok_hash(token), user_id=user_id, created_at=now, last_seen=now, ip=ip[:64], agent=agent[:160]))
    return token


def lookup(db: Database, token: str | None, idle_s: float, max_s: float, now: float | None = None) -> Principal | None:
    if not token:
        return None
    now = int(time.time() if now is None else now)
    sid = _tok_hash(token)
    with db.session() as s:
        sess = s.get(AuthSession, sid)
        if sess is None:
            return None
        if now - sess.last_seen > idle_s or now - sess.created_at > max_s:
            s.delete(sess)
            return None
        user = s.get(User, sess.user_id)
        if user is None or user.disabled:
            return None
        if now - sess.last_seen > 60:  # touch at most once a minute: fewer writes on flash storage
            sess.last_seen = now
        return Principal(user.id, user.username, user.role, sid)


def revoke(db: Database, token: str | None = None, user_id: int | None = None, keep: str | None = None) -> int:
    with db.session() as s:
        q = delete(AuthSession)
        if token:
            q = q.where(AuthSession.id == _tok_hash(token))
        elif user_id is not None:
            q = q.where(AuthSession.user_id == user_id)
            if keep:
                q = q.where(AuthSession.id != keep)
        else:
            return 0
        return s.execute(q).rowcount or 0


def purge_expired(db: Database, idle_s: float, max_s: float, now: float | None = None) -> int:
    now = int(time.time() if now is None else now)
    with db.session() as s:
        return s.execute(delete(AuthSession).where((AuthSession.last_seen < now - idle_s) | (AuthSession.created_at < now - max_s))).rowcount or 0


# --------------------------------------------------------------------- users
def count_users(db: Database) -> int:
    with db.session() as s:
        return len(list(s.scalars(select(User.id))))


def create_user(db: Database, username: str, password: str, role: str) -> int:
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        raise ValueError("username must be 3-48 characters: a-z, 0-9, . _ -")
    if role not in ROLES:
        raise ValueError("role must be admin, operator or viewer")
    problem = password_problem(password, username)
    if problem:
        raise ValueError(problem)
    with db.session() as s:
        if s.scalar(select(User).where(User.username == username)):
            raise ValueError("username already exists")
        u = User(username=username, password_hash=hash_password(password), role=role, created_at=int(time.time()))
        s.add(u)
        s.flush()
        return u.id


def authenticate(db: Database, username: str, password: str) -> User | None:
    username = username.strip().lower()
    with db.session() as s:
        u = s.scalar(select(User).where(User.username == username))
        ok = verify_password(password, u.password_hash if u else _DUMMY)
        if u is None or not ok or u.disabled:
            return None
        u.last_login_ts = int(time.time())
        s.flush()
        s.expunge(u)
        return u


def admin_count(db: Database, excluding: int | None = None) -> int:
    with db.session() as s:
        return len([u for u in s.scalars(select(User).where(User.role == "admin", User.disabled.is_(False))) if u.id != excluding])


# ------------------------------------------------------------- setup code
def setup_code_path(data_dir: Path) -> Path:
    return data_dir / "setup_code.txt"


def ensure_setup_code(data_dir: Path) -> str:
    """One-time code that must be presented to create the first administrator."""
    p = setup_code_path(data_dir)
    if p.exists():
        return p.read_text().strip()
    code = secrets.token_hex(4)
    p.write_text(code + "\n")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return code


def consume_setup_code(data_dir: Path, given: str) -> bool:
    p = setup_code_path(data_dir)
    if not p.exists() or not hmac.compare_digest(p.read_text().strip(), (given or "").strip()):
        return False
    p.unlink()
    return True


# ------------------------------------------------------------------- policy
OPERATOR_WRITE = [
    r"^/api/irrigation/zones/[^/]+/(run|stop)$", r"^/api/actuators/[^/]+/command$", r"^/api/climate/outputs/[^/]+/release$",
    r"^/api/climate/windows/[^/]+/(position|release)$", r"^/api/safety/estop/reset$", r"^/api/alerts/[^/]+/(ack|clear)$",
    r"^/api/maintenance/[^/]+/done$", r"^/api/diagnostics/run$", r"^/api/sensors/[^/]+/test-read$",
]
ANY_USER_WRITE = [r"^/api/safety/estop$", r"^/api/auth/(logout|password)$", r"^/api/diagnostics/(diagnose|explain)$"]
ADMIN_READ = [r"^/api/users", r"^/api/audit", r"^/api/backup"]
PUBLIC = [r"^/api/health$", r"^/api/auth/(status|login|setup)$"]
_C = lambda pats: [re.compile(p) for p in pats]  # noqa: E731
_OP, _ANY, _ADMR, _PUB = _C(OPERATOR_WRITE), _C(ANY_USER_WRITE), _C(ADMIN_READ), _C(PUBLIC)
MUTATING = {"POST", "PUT", "DELETE", "PATCH"}


def is_public(path: str) -> bool:
    return any(r.match(path) for r in _PUB)


def required_role(method: str, path: str) -> str:
    """Minimum role for an authenticated request. Anything not listed needs an administrator."""
    if method in MUTATING:
        if any(r.match(path) for r in _ANY):
            return "viewer"
        if any(r.match(path) for r in _OP):
            return "operator"
        return "admin"
    if any(r.match(path) for r in _ADMR):
        return "admin"
    return "viewer"


def audit(db: Database, p: Principal | None, ip: str, method: str, path: str, status: int, detail: str = "") -> None:
    with db.session() as s:
        s.add(AuditLog(ts=int(time.time()), username=p.username if p else "", role=p.role if p else "", ip=ip[:64], method=method,
                       path=path[:200], status=status, detail=detail[:200]))
