"""HTTP security layer: authentication, roles, CSRF defence, request limits, audit, headers."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services import auth

log = logging.getLogger(__name__)

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
           "Content-Security-Policy": CSP, "Permissions-Policy": "geolocation=(), microphone=(), camera=()"}
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "gcc"


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _deny(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        st = app.state
        path, method = request.url.path, request.method
        is_api = path.startswith("/api/")

        def finish(resp):
            for k, v in HEADERS.items():
                resp.headers.setdefault(k, v)
            if is_api:
                resp.headers["Cache-Control"] = "no-store"
            return resp

        # request size (declared length; handlers read bodies only after this check)
        try:
            length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            return finish(_deny(400, "bad content-length"))
        limit = st.settings.max_upload_mb if path == "/api/backup/restore-upload" else st.settings.max_body_mb
        if length > limit * 1024 * 1024:
            return finish(_deny(413, f"request body larger than {limit:g} MB"))

        principal = None
        if is_api and st.settings.auth_required:
            principal = auth.lookup(st.db, request.cookies.get(auth.COOKIE), st.settings.session_idle_hours * 3600,
                                    st.settings.session_max_days * 86400)
            if method in auth.MUTATING:  # CSRF: custom header (not sendable cross-site without CORS) + same-origin check
                if request.headers.get(CSRF_HEADER, "").lower() != CSRF_VALUE:
                    return finish(_deny(403, "missing X-Requested-With header"))
                origin = request.headers.get("origin")
                if origin and urlparse(origin).netloc != request.headers.get("host", ""):
                    return finish(_deny(403, "cross-origin request refused"))
            if not auth.is_public(path):
                if principal is None:
                    return finish(_deny(401, "authentication required"))
                need = auth.required_role(method, path)
                if auth.ROLES[principal.role] < auth.ROLES[need]:
                    auth.audit(st.db, principal, client_ip(request), method, path, 403, f"needs {need}")
                    return finish(_deny(403, f"this action needs the '{need}' role"))
        request.state.principal = principal
        response = await call_next(request)
        if is_api and st.settings.auth_required and method in auth.MUTATING and principal is not None and not path.startswith("/api/auth/"):
            try:
                auth.audit(st.db, principal, client_ip(request), method, path, response.status_code)
            except Exception:  # noqa: BLE001 - auditing must never break a request
                log.exception("audit write failed")
        return finish(response)
