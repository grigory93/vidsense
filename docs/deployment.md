# Production deployment (VM)

VidSense is designed to run on a single VM behind a TLS reverse proxy. The [`deploy/`](../deploy/) directory contains ready-to-use templates.

## Quick checklist

1. **Set `APP_SECRET_KEY`** in `.env` (the app refuses to start with the default placeholder).  
   Generate one: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. **Set `APP_ALLOWED_HOSTS`** to your public domain plus localhost, e.g. `APP_ALLOWED_HOSTS=vidsense.example.com,localhost,127.0.0.1`. If this is missing or wrong, requests arriving with the domain `Host` header get a **400 Bad Request** with no body — the most common cause of "blank page after login."
3. **Set `APP_DEBUG=false`** — disables `/docs`, `/redoc`, `/openapi.json` and hides request bodies from error responses.
4. **TLS + reverse proxy** — copy [`deploy/Caddyfile`](../deploy/Caddyfile), replace `YOUR_DOMAIN`, and configure `basicauth` credentials. Caddy handles Let's Encrypt automatically.
5. **Bind address** — the app binds to `127.0.0.1:8000` by default; only the reverse proxy should be internet-facing.
6. **Firewall** — allow ports **443** (and **80** for ACME). Restrict SSH source IPs, use key-only auth. Do not expose port 8000.
7. **Non-root service user** — copy [`deploy/vidsense.service`](../deploy/vidsense.service) to `/etc/systemd/system/`, create a `vidsense` user, and adjust paths. See comments in the file.
8. **File permissions** — `chmod 600 .env`; ensure `data/` is owned by the service user and not world-readable.

## Access control (v1: proxy-level auth)

The v1 approach uses **Caddy `basicauth`** (or nginx `auth_basic`) in front of the entire site. Browser `fetch()` calls to `/api` work transparently because same-origin requests include Basic Auth credentials automatically.

For programmatic API clients that need direct `/api` access without the proxy password, a future enhancement (Path B) would add application-level API key authentication. See comments in [`deploy/Caddyfile`](../deploy/Caddyfile) for details.

The sample Caddy config also includes a basic CSP, request-size limit, and upstream dial/header timeouts. Stock Caddy does not include rate limiting by default, so that is intentionally deferred for a later version.

## Deployment files

| File | Purpose |
|------|---------|
| [`deploy/Caddyfile`](../deploy/Caddyfile) | TLS, basicauth, security headers, CSP, request-size limit, reverse proxy to `127.0.0.1:8000` |
| [`deploy/vidsense.service`](../deploy/vidsense.service) | systemd unit: non-root user, restart policy, hardening options |
| [`deploy/bootstrap.sh`](../deploy/bootstrap.sh) | Idempotent VM setup script (Ubuntu): installs Python, uv, Caddy, clones repo, creates service user |

## Related

- Environment template and production hints: [`.env.example`](../.env.example)
- Application settings: [`app/config.py`](../app/config.py)
