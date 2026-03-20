# Production deployment (VM)

VidSense is designed to run on a single VM behind a TLS reverse proxy. The [`deploy/`](../deploy/) directory contains ready-to-use templates.

## Quick checklist

1. **Set `APP_SECRET_KEY`** in `.env` (the app refuses to start with the default placeholder).  
   Generate one: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. **Set `APP_DEBUG=false`** — disables `/docs`, `/redoc`, `/openapi.json` and hides request bodies from error responses.
3. **TLS + reverse proxy** — copy [`deploy/Caddyfile`](../deploy/Caddyfile), replace `YOUR_DOMAIN`, and configure `basicauth` credentials. Caddy handles Let's Encrypt automatically.
4. **Bind address** — the app binds to `127.0.0.1:8000` by default; only the reverse proxy should be internet-facing.
5. **Firewall** — allow ports **443** (and **80** for ACME). Restrict SSH source IPs, use key-only auth. Do not expose port 8000.
6. **Non-root service user** — copy [`deploy/vidsense.service`](../deploy/vidsense.service) to `/etc/systemd/system/`, create a `vidsense` user, and adjust paths. See comments in the file.
7. **File permissions** — `chmod 600 .env`; ensure `data/` is owned by the service user and not world-readable.

## Access control (v1: proxy-level auth)

The v1 approach uses **Caddy `basicauth`** (or nginx `auth_basic`) in front of the entire site. Browser `fetch()` calls to `/api` work transparently because same-origin requests include Basic Auth credentials automatically.

For programmatic API clients that need direct `/api` access without the proxy password, a future enhancement (Path B) would add application-level API key authentication. See comments in [`deploy/Caddyfile`](../deploy/Caddyfile) for details.

## Deployment files

| File | Purpose |
|------|---------|
| [`deploy/Caddyfile`](../deploy/Caddyfile) | TLS, basicauth, security headers, reverse proxy to `127.0.0.1:8000` |
| [`deploy/vidsense.service`](../deploy/vidsense.service) | systemd unit: non-root user, restart policy, hardening options |

## Related

- Environment template and production hints: [`.env.example`](../.env.example)
- Application settings: [`app/config.py`](../app/config.py)
