# Security

Everything below is implemented and covered by tests (`backend/tests/test_security.py`, 24 tests), but **it has not had an independent security review or penetration test**. Treat the application as suitable for a private network, not for exposure to the internet.

## Model

The interface speaks HTTP on your local network. Anyone who could reach it before could water, change settings or reset the e-stop; now every request needs a signed-in user with a sufficient role.

| Role | May |
|---|---|
| **viewer** | read everything except users, audit and backups; press the **emergency stop** |
| **operator** | + water now/stop, switch outputs, move windows, release overrides, reset the e-stop, acknowledge/clear alerts, test-read sensors, mark maintenance done |
| **admin** | everything, including configuration, commissioning attestations, users, audit log, backups and restore |

Rule of thumb enforced by a test: a mutating endpoint nobody classified is **administrator-only**, and a test lists exactly which endpoints are open to lower roles.

## First start

With no users, the application writes a one-time setup code to `setup_code.txt` in the data folder (mode 600) and logs its path. The web interface asks for it to create the first administrator; the code is then deleted. Setup attempts are rate-limited. (On the Raspberry Pi service: `sudo cat /var/lib/greenhouse/setup_code.txt`.)

## What is protected how

- **Passwords:** at least 10 characters, not containing the username, not trivially repetitive; stored as salted **scrypt** hashes. Failed and unknown-user logins take the same time and return the same message.
- **Sessions:** random 256-bit tokens in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` over HTTPS); only a SHA-256 of the token is stored. Idle timeout 12 h, absolute 7 days (`GCC_SESSION_IDLE_HOURS`, `GCC_SESSION_MAX_DAYS`). Changing a password, role or status signs that user's other sessions out; logout ends the session on the server.
- **Brute force:** 5 failed sign-ins for an account or 10 from one address lock further attempts for 5 minutes (memory only, resets on restart).
- **CSRF:** every state-changing request must carry `X-Requested-With: gcc` (a header another website cannot add) and, if an `Origin` header is present, it must match the host. Together with `SameSite=Strict` this blocks cross-site requests.
- **Audit log:** sign-ins, failed sign-ins, denied actions and every change request by a signed-in user (method, path, status, user, address; never passwords or bodies), kept across restores. Admin page.
- **Headers:** `Content-Security-Policy` (scripts only from the application itself, no framing), `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` for the API. The shipped interface works under this policy (checked in a browser, no violations).
- **Limits:** request bodies over 2 MB are refused (200 MB for backup upload).
- **Hardware safety is separate:** software authentication does not replace the hardware emergency stop and protections (SAFETY.md).

## What it does NOT do

- **No TLS by itself.** Passwords and the session cookie cross the network in clear over plain HTTP. Anyone on the same network segment (or Wi-Fi) could capture them. Either keep the interface on a trusted wired network, or put it behind a TLS reverse proxy and set `GCC_COOKIE_SECURE=true`. An example (**untested**) Caddy setup: run the application on `127.0.0.1:8000` (change `--host` in the service file) and give Caddy `greenhouse.local { tls internal; reverse_proxy 127.0.0.1:8000 }`. Behind a proxy the rate limiter sees the proxy's address.
- No two-factor authentication, no password reset by email (an administrator resets passwords; if the last admin is locked out, stop the service, remove the `users` rows with `sqlite3`, and set up again with a new code).
- Rate-limiter state and failed-login counts are lost on restart.
- Backups contain password hashes (BACKUP_RESTORE.md): protect them like the database itself.
- `GCC_AUTH_REQUIRED=false` disables everything above. Use it only on an isolated development computer.
- Supply-chain: dependencies are pinned loosely (`requirements.txt`); run `pip list --outdated` / `pip-audit` yourself periodically. Not done here.

## Network hardening checklist

1. Keep port 8000 off the internet; do not port-forward it. Prefer a firewall allowing your LAN only (INSTALLATION.md).
2. Use a strong, unique administrator password; create operator/viewer accounts for everyone else.
3. Use HTTPS (reverse proxy) if the network is shared or wireless.
4. Keep Raspberry Pi OS and the Python packages updated.
5. Copy backups off the device; review the audit log occasionally.
