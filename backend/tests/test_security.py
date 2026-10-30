import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.models import AuthSession, User
from app.core.settings import Settings
from app.main import create_app
from app.services import auth

H = {"X-Requested-With": "gcc"}
PW = "correct-horse-battery"


@pytest.fixture
def secure(tmp_path):
    s = Settings(data_dir=tmp_path, autostart_ingest=False, autostart_engine=False, serve_frontend=False, auth_required=True,
                 poll_interval_s=1, flush_interval_s=1)
    app = create_app(s)
    with TestClient(app) as c:
        c.tmp = tmp_path
        yield c


def post(c, path, **kw):
    return c.post(path, headers={**H, **kw.pop("headers", {})}, **kw)


def put(c, path, **kw):
    return c.put(path, headers=H, **kw)


def setup(c, user="admin1", pw=PW):
    code = auth.setup_code_path(c.tmp).read_text().strip()
    r = post(c, "/api/auth/setup", json={"code": code, "username": user, "password": pw})
    assert r.status_code == 200, r.text
    return r


def login_as(c, user, pw=PW):
    c.cookies.clear()
    r = post(c, "/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return r


def add_user(c, name, role, pw=PW):
    r = post(c, "/api/users", json={"username": name, "password": pw, "role": role})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def team(secure):
    """admin1 (signed in), plus operator1 and viewer1 accounts."""
    setup(secure)
    add_user(secure, "operator1", "operator")
    add_user(secure, "viewer1", "viewer")
    return secure



def api_ops(app):
    """(METHOD, path, sample_path) for every documented API operation."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/api/"):
            continue
        sample = re.sub(r"\{[^}]+\}", "x1", path)
        if sample.endswith(".x1"):
            sample = sample[:-3] + ".csv"
        for m in ops:
            out.append((m.upper(), path, sample))
    return out


# ------------------------------------------------------------ first run

def test_everything_but_health_and_login_needs_a_session(secure):
    assert secure.get("/api/health").status_code == 200
    st = secure.get("/api/auth/status").json()
    assert st["auth_required"] and st["setup_needed"] and not st["authenticated"] and st["user"] is None
    for path in ("/api/sensors", "/api/config", "/api/irrigation/status", "/api/backup", "/api/users", "/api/audit", "/api/shopping/export.csv"):
        assert secure.get(path).status_code == 401, path
    assert secure.get("/api/openapi.json").status_code in (401, 404)


def test_first_administrator_needs_the_one_time_setup_code(secure):
    assert auth.setup_code_path(secure.tmp).exists()
    bad = post(secure, "/api/auth/setup", json={"code": "nope", "username": "admin1", "password": PW})
    assert bad.status_code == 403
    r = setup(secure)
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie and "secure" not in set_cookie
    assert not auth.setup_code_path(secure.tmp).exists()            # single use
    assert secure.get("/api/auth/status").json()["user"] == {"username": "admin1", "role": "admin"}
    assert secure.get("/api/sensors").status_code == 200
    assert post(secure, "/api/auth/setup", json={"code": "x", "username": "evil", "password": PW}).status_code == 409


def test_weak_setup_password_is_refused_and_a_new_code_issued(secure):
    code = auth.setup_code_path(secure.tmp).read_text().strip()
    for bad_pw, bad_user in (("short", "admin1"), ("admin1-admin1", "admin1"), ("aaaaaaaaaaaa", "admin1"), (PW, "A!")):
        assert post(secure, "/api/auth/setup", json={"code": code, "username": bad_user, "password": bad_pw}).status_code == 422
        code = auth.setup_code_path(secure.tmp).read_text().strip()      # consumed code was replaced
    assert post(secure, "/api/auth/setup", json={"code": code, "username": "admin1", "password": PW}).status_code == 200


def test_setup_attempts_are_rate_limited(secure):
    codes = [post(secure, "/api/auth/setup", json={"code": f"bad{i}", "username": "a1b", "password": PW}).status_code for i in range(12)]
    assert 429 in codes
    assert post(secure, "/api/auth/setup", json={"code": auth.setup_code_path(secure.tmp).read_text().strip(), "username": "admin1", "password": PW}).status_code == 429


# --------------------------------------------------------------- login

def test_login_logout_and_generic_failure(secure):
    setup(secure)
    secure.cookies.clear()
    a = post(secure, "/api/auth/login", json={"username": "admin1", "password": "wrong-password-1"})
    b = post(secure, "/api/auth/login", json={"username": "nobody", "password": "wrong-password-1"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()      # no user enumeration
    assert secure.get("/api/sensors").status_code == 401
    r = post(secure, "/api/auth/login", json={"username": "ADMIN1", "password": PW})
    assert r.status_code == 200 and r.json() == {"username": "admin1", "role": "admin"}
    token = secure.cookies.get(auth.COOKIE)
    assert secure.get("/api/sensors").status_code == 200
    assert post(secure, "/api/auth/logout").status_code == 200
    secure.cookies.set(auth.COOKIE, token)
    assert secure.get("/api/sensors").status_code == 401                       # the server really ended the session


def test_brute_force_lockout(secure):
    setup(secure)
    add_user(secure, "second1", "viewer")
    secure.cookies.clear()
    for _ in range(5):
        assert post(secure, "/api/auth/login", json={"username": "second1", "password": "wrong-password-1"}).status_code == 401
    r = post(secure, "/api/auth/login", json={"username": "second1", "password": PW})     # correct password, still locked
    assert r.status_code == 429 and "try again" in r.json()["detail"]
    ok = post(secure, "/api/auth/login", json={"username": "admin1", "password": PW})     # other accounts unaffected
    assert ok.status_code == 200


def test_rate_limiter_windowing():
    rl = auth.RateLimiter(per_ip=3, per_user=2, window_s=100, lock_s=50)
    assert rl.blocked("1.1.1.1", "u", now=0) == 0
    rl.fail("1.1.1.1", "u", now=1)
    rl.fail("1.1.1.1", "u", now=2)
    assert rl.blocked("9.9.9.9", "u", now=3) == pytest.approx(49)              # user limit reached from any address
    assert rl.blocked("1.1.1.1", "other", now=3) == 0
    assert rl.blocked("9.9.9.9", "u", now=60) == 0                              # lock elapsed
    rl.ok("1.1.1.1", "u")
    assert rl.blocked("9.9.9.9", "u", now=3) == 0
    rl.fail("2.2.2.2", "a", now=0); rl.fail("2.2.2.2", "b", now=1); rl.fail("2.2.2.2", "c", now=2)
    assert rl.blocked("2.2.2.2", "z", now=3) > 0 and rl.blocked("2.2.2.2", "z", now=200) == 0   # old failures expire


def test_sessions_expire_idle_and_absolute(secure):
    setup(secure)
    uid = 1
    tok = auth.create_session(secure.app.state.db, uid, "x", "agent", now=1000)
    db = secure.app.state.db
    assert auth.lookup(db, tok, idle_s=3600, max_s=86400, now=1000 + 3000).username == "admin1"
    assert auth.lookup(db, tok, idle_s=3600, max_s=86400, now=1000 + 3000 + 3601) is None      # idle (and now deleted)
    tok2 = auth.create_session(db, uid, "x", "agent", now=0)
    for t in range(0, 90000, 3000):                                                              # keeps being used
        p = auth.lookup(db, tok2, idle_s=3600, max_s=86400, now=t)
        if t > 86400:
            assert p is None
            break
        assert p is not None
    assert auth.lookup(db, None, 1, 1) is None and auth.lookup(db, "garbage", 1, 1) is None


def test_secrets_are_not_stored_in_the_clear(secure):
    setup(secure)
    token = secure.cookies.get(auth.COOKIE)
    with secure.app.state.db.session() as s:
        u = s.scalar(select(User))
        assert u.password_hash.startswith("scrypt$") and PW not in u.password_hash
        ids = [x.id for x in s.scalars(select(AuthSession))]
    assert token not in ids and auth._tok_hash(token) in ids
    assert auth.hash_password(PW) != auth.hash_password(PW)                       # salted
    assert auth.verify_password(PW, u.password_hash) and not auth.verify_password(PW + "x", u.password_hash)
    assert not auth.verify_password(PW, "garbage") and not auth.verify_password(PW, "scrypt$1$2$3$zz$yy")


def test_cookie_is_secure_over_https(tmp_path):
    s = Settings(data_dir=tmp_path, autostart_ingest=False, autostart_engine=False, serve_frontend=False, auth_required=True)
    with TestClient(create_app(s), base_url="https://testserver") as c:
        c.tmp = tmp_path
        assert "secure" in setup(c).headers["set-cookie"].lower()


# ---------------------------------------------------------------- CSRF

def test_state_changing_requests_need_the_header_and_same_origin(team):
    assert team.post("/api/safety/estop").status_code == 403                                         # no header
    assert team.put("/api/config", json=team.get("/api/config").json()).status_code == 403
    assert team.post("/api/safety/estop", headers={**H, "Origin": "https://evil.example"}).status_code == 403
    assert team.get("/api/config").status_code == 200                                                # reads are unaffected
    same = team.post("/api/maintenance/check", headers={**H, "Origin": "http://testserver"})
    assert same.status_code == 200
    assert team.post("/api/auth/logout").status_code == 403                                          # even logout is protected


def test_samesite_cookie_blocks_cross_site_use_by_design(team):
    c = next(v for k, v in team.cookies.items() if k == auth.COOKIE)
    assert c and len(c) > 30                                                                         # high-entropy token
    assert len({auth.create_session(team.app.state.db, 1, "", "") for _ in range(20)}) == 20


# ---------------------------------------------------------------- roles

def test_roles_are_enforced(team):
    login_as(team, "viewer1")
    assert team.get("/api/sensors").status_code == 200
    assert team.get("/api/users").status_code == 403 and team.get("/api/audit").status_code == 403 and team.get("/api/backup").status_code == 403
    assert put(team, "/api/config", json=team.get("/api/config").json()).status_code == 403
    assert post(team, "/api/irrigation/zones/soil_a/run", json={}).status_code == 403
    assert post(team, "/api/safety/estop").status_code == 200                                          # anyone signed in may press e-stop
    assert post(team, "/api/safety/estop/reset", json={"confirm": True}).status_code == 403

    login_as(team, "operator1")
    r = post(team, "/api/irrigation/zones/soil_a/run", json={"duration_s": 5})
    assert r.status_code in (200, 409)                                                                 # allowed (may be refused by interlocks)
    assert post(team, "/api/safety/estop/reset", json={"confirm": True}).status_code == 200
    assert post(team, "/api/actuators/sim_valve_a/command", json={"state": "off"}).status_code == 200
    assert put(team, "/api/config", json=team.get("/api/config").json()).status_code == 403
    assert post(team, "/api/sensors", json={}).status_code == 403
    assert post(team, "/api/safety/checks/watchdog/attest", json={"note": "a note that is long enough"}).status_code == 403
    assert post(team, "/api/users", json={"username": "x1x", "password": PW, "role": "admin"}).status_code == 403
    assert team.get("/api/users").status_code == 403

    login_as(team, "admin1")
    assert team.get("/api/users").status_code == 200 and team.get("/api/backup").status_code == 200
    assert put(team, "/api/config", json=team.get("/api/config").json()).status_code == 200


def test_every_route_has_a_deliberate_role(team):
    """A new mutating endpoint that nobody classified must default to administrator-only."""
    below = {path for m, path, sample in api_ops(team.app) if m in auth.MUTATING and not auth.is_public(sample) and auth.required_role(m, sample) != "admin"}
    assert below == {
        "/api/irrigation/zones/{zone_id}/run", "/api/irrigation/zones/{zone_id}/stop", "/api/actuators/{act_id}/command",
        "/api/climate/outputs/{oid}/release", "/api/climate/windows/{wid}/position", "/api/climate/windows/{wid}/release",
        "/api/safety/estop", "/api/safety/estop/reset", "/api/alerts/{alert_id}/ack", "/api/alerts/{alert_id}/clear",
        "/api/maintenance/{task_id}/done", "/api/diagnostics/run", "/api/diagnostics/explain", "/api/diagnostics/diagnose",
        "/api/sensors/{sensor_id}/test-read", "/api/auth/logout", "/api/auth/password"}


def test_viewer_cannot_reach_any_other_mutating_route(team):
    login_as(team, "viewer1")
    checked = 0
    for m, path, sample in api_ops(team.app):
        if m in auth.MUTATING and not auth.is_public(sample) and auth.required_role(m, sample) in ("admin", "operator"):
            resp = team.request(m, sample, headers=H, json={})
            assert resp.status_code == 403, (m, path, resp.status_code)
            checked += 1
    assert checked > 60


def test_operator_cannot_reach_admin_routes(team):
    login_as(team, "operator1")
    checked = 0
    for m, path, sample in api_ops(team.app):
        if not auth.is_public(sample) and auth.required_role(m, sample) == "admin":
            resp = team.request(m, sample, headers=H if m in auth.MUTATING else {}, json={} if m in auth.MUTATING else None)
            assert resp.status_code == 403, (m, path, resp.status_code)
            checked += 1
    assert checked > 60


# ------------------------------------------------------ user management

def test_user_management_rules(team):
    users = {u["username"]: u for u in team.get("/api/users").json()}
    admin_id = users["admin1"]["id"]
    assert post(team, "/api/users", json={"username": "viewer1", "password": PW, "role": "viewer"}).status_code == 409
    assert post(team, "/api/users", json={"username": "okay1", "password": "short", "role": "viewer"}).status_code == 422
    assert post(team, "/api/users", json={"username": "okay1", "password": PW, "role": "emperor"}).status_code == 422
    assert team.delete(f"/api/users/{admin_id}", headers=H).status_code == 409                          # own account / last admin
    assert put(team, f"/api/users/{admin_id}", json={"role": "viewer"}).status_code == 409             # last admin
    assert put(team, f"/api/users/{admin_id}", json={"disabled": True}).status_code == 409
    second = add_user(team, "admin2", "admin")
    assert put(team, f"/api/users/{second}", json={"role": "operator"}).status_code == 200            # another admin remains
    assert put(team, f"/api/users/{second}", json={"role": "admin"}).status_code == 200
    assert team.delete("/api/users/9999", headers=H).status_code == 404

    vid = users["viewer1"]["id"]
    login_as(team, "viewer1")
    old = team.cookies.get(auth.COOKIE)
    login_as(team, "admin1")
    assert put(team, f"/api/users/{vid}", json={"disabled": True}).status_code == 200
    team.cookies.set(auth.COOKIE, old)
    assert team.get("/api/sensors").status_code == 401                                                 # session ended with the disable
    assert post(team, "/api/auth/login", json={"username": "viewer1", "password": PW}).status_code == 401
    login_as(team, "admin1")
    assert put(team, f"/api/users/{vid}", json={"disabled": False, "password": "another-long-pass"}).status_code == 200
    assert login_as(team, "viewer1", "another-long-pass").status_code == 200
    login_as(team, "admin1")
    assert team.delete(f"/api/users/{vid}", headers=H).status_code == 200


def test_password_change_ends_other_sessions(team):
    other = TestClient(team.app)
    other.tmp = team.tmp
    assert post(other, "/api/auth/login", json={"username": "admin1", "password": PW}).status_code == 200
    assert other.get("/api/sensors").status_code == 200
    assert post(team, "/api/auth/password", json={"current": "wrong-password-1", "new": "brand-new-passphrase"}).status_code == 403
    assert post(team, "/api/auth/password", json={"current": PW, "new": "short"}).status_code == 422
    r = post(team, "/api/auth/password", json={"current": PW, "new": "brand-new-passphrase"})
    assert r.status_code == 200 and r.json()["other_sessions_ended"] == 1
    assert team.get("/api/sensors").status_code == 200 and other.get("/api/sensors").status_code == 401
    assert login_as(team, "admin1", "brand-new-passphrase").status_code == 200
    assert post(team, "/api/auth/login", json={"username": "admin1", "password": PW}).status_code == 401


# ------------------------------------------------------------------ audit

def test_audit_trail(team):
    post(team, "/api/maintenance", json={"title": "Check the filter", "interval_days": 30})
    team.get("/api/sensors")                                                                              # reads are not audited
    login_as(team, "viewer1")
    post(team, "/api/irrigation/zones/soil_a/run", json={})                                               # denied
    post(team, "/api/auth/login", json={"username": "viewer1", "password": "wrong-password-1"})            # failed login
    login_as(team, "admin1")
    rows = team.get("/api/audit").json()
    paths = [(r["method"], r["path"], r["status"], r["username"]) for r in rows]
    assert ("POST", "/api/maintenance", 201, "admin1") in paths
    assert ("POST", "/api/irrigation/zones/soil_a/run", 403, "viewer1") in paths
    assert any(r["status"] == 401 and "failed login: viewer1" in r["detail"] for r in rows)
    assert any(r["path"] == "/api/auth/setup" and "first administrator" in r["detail"] for r in rows)
    assert not any(r["path"] == "/api/sensors" for r in rows)
    assert all(PW not in str(r) for r in rows)                                                           # no secrets in the log


# ---------------------------------------------------- headers and limits

def test_security_headers_and_caching(team):
    r = team.get("/api/sensors")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"] and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "script-src 'self'" in r.headers["content-security-policy"] and "unsafe-eval" not in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"
    assert team.get("/api/health").headers["x-frame-options"] == "DENY"                                    # also on public routes
    assert secure_unauth(team).headers["x-content-type-options"] == "nosniff"                              # and on errors


def secure_unauth(team):
    return TestClient(team.app).get("/api/sensors")


def test_large_responses_are_compressed(team):
    r = team.get("/api/encyclopedia/rpi5", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"


def test_request_size_limits(team):
    big = {"X-Requested-With": "gcc", "Content-Length": str(3 * 1024 * 1024)}
    r = team.post("/api/maintenance", headers=big, content=b"{}")
    assert r.status_code == 413
    assert post(team, "/api/auth/login", json={"username": "a" * 70, "password": "x"}).status_code in (401, 403, 422)


def test_auth_can_be_switched_off_for_a_private_machine(client):
    st = client.get("/api/auth/status").json()
    assert not st["auth_required"] and st["authenticated"] and not st["setup_needed"]
    assert client.get("/api/sensors").status_code == 200
    assert client.post("/api/safety/estop").status_code == 200                                              # no header needed
    assert client.post("/api/auth/setup", json={"code": "x", "username": "abc", "password": PW}).status_code == 409


def test_unauthenticated_gets_never_500(secure):
    openapi = secure.app.openapi()
    for path, ops in openapi["paths"].items():
        if "get" in ops and "{" not in path:
            code = secure.get(path).status_code
            assert code in (200, 401), (path, code)


def test_api_docs_are_off_by_default(secure):
    for p in ("/docs", "/redoc", "/openapi.json", "/api/openapi.json"):
        assert secure.get(p).status_code in (401, 404), p


def test_rate_limiter_memory_is_bounded():
    rl = auth.RateLimiter()
    for i in range(20000):                                   # an attacker trying endless random usernames
        rl.fail("6.6.6.6", f"user{i}", now=1000.0 + i * 0.001)
    assert len(rl._fails) <= 10001
    assert rl.blocked("6.6.6.6", "x") >= 0
