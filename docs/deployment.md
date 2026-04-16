# Production deployment (VM)

VidSense is designed to run on a single VM behind a TLS reverse proxy. The [`deploy/`](../deploy/) directory contains ready-to-use templates.

## Quick checklist

1. **Set `APP_SECRET_KEY`** in `.env` (the app refuses to start with the default placeholder).  
   Generate one: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. **Set `YOUTUBE_API_KEY`** in `.env` — required for YouTube Data API v3 (metadata, tags, comments context); the app refuses to start without it. See [YouTube Data API key](../README.md#youtube-data-api-key) in the README and [`.env.example`](../.env.example).
3. **Set `APP_ALLOWED_HOSTS`** to your public domain plus localhost, e.g. `APP_ALLOWED_HOSTS=vidsense.info,localhost,127.0.0.1`. If this is missing or wrong, requests arriving with the domain `Host` header get a **400 Bad Request** with no body — the most common cause of "blank page after login."
4. **Set `APP_DEBUG=false`** — disables `/docs`, `/redoc`, `/openapi.json` and hides request bodies from error responses.
5. **TLS + reverse proxy** — copy [`deploy/Caddyfile`](../deploy/Caddyfile), replace `YOUR_DOMAIN`, and configure `basicauth` credentials. Caddy handles Let's Encrypt automatically.
6. **Bind address** — the app binds to `127.0.0.1:8000` by default; only the reverse proxy should be internet-facing.
7. **Firewall** — allow ports **443** (and **80** for ACME). Restrict SSH source IPs, use key-only auth. Do not expose port 8000.
8. **Non-root service user** — copy [`deploy/vidsense.service`](../deploy/vidsense.service) to `/etc/systemd/system/`, create a `vidsense` user, and adjust paths. See comments in the file.
9. **File permissions** — `chmod 600 .env`; ensure `data/` is owned by the service user and not world-readable.

## Logging

The app does **not** write logs to a file by itself. [`main.py`](../main.py) configures Python logging with `logging.basicConfig(...)`, which sends messages to **stderr** at INFO level (or DEBUG when `APP_DEBUG=true`).

**Production (systemd):** The sample [`deploy/vidsense.service`](../deploy/vidsense.service) sets `StandardOutput=journal` and `StandardError=journal`, so process output is collected by **journald**. Follow logs with:

```bash
sudo journalctl -u vidsense -f
```

**Manual runs — capture logs in a file** by redirecting stderr (Python logging uses stderr) and optionally stdout:

```bash
# See output in the terminal and append to a file
uv run uvicorn main:app --host 127.0.0.1 --port 8000 2>&1 | tee -a app.log

# Stderr only to a file
uv run uvicorn main:app --host 127.0.0.1 --port 8000 2>app.log

# Stdout and stderr together in one file
uv run uvicorn main:app --host 127.0.0.1 --port 8000 >app.log 2>&1
```

The same redirects apply if you start via `uv run python main.py` (the `__main__` block runs uvicorn).

## Access control (v1: proxy-level auth)

The v1 approach uses **Caddy `basicauth`** (or nginx `auth_basic`) in front of the entire site. Browser `fetch()` calls to `/api` work transparently because same-origin requests include Basic Auth credentials automatically.

For programmatic API clients that need direct `/api` access without the proxy password, a future enhancement (Path B) would add application-level API key authentication. See comments in [`deploy/Caddyfile`](../deploy/Caddyfile) for details.

The sample Caddy config also includes a basic CSP, request-size limit, and upstream dial/header timeouts. Stock Caddy does not include rate limiting by default, so that is intentionally deferred for a later version.

## Deployment files

| File | Purpose |
|------|---------|
| [`deploy/Caddyfile`](../deploy/Caddyfile) | TLS, basicauth, security headers, CSP, request-size limit, reverse proxy to `127.0.0.1:8000` |
| [`deploy/vidsense.service`](../deploy/vidsense.service) | systemd unit: non-root user, restart policy, hardening options |
| [`deploy/bootstrap.sh`](../deploy/bootstrap.sh) | Idempotent VM setup script (Ubuntu): uv, Caddy, clone repo, `uv python install` + `uv sync`, service user |

## Related

- Environment template and production hints: [`.env.example`](../.env.example)
- Application settings: [`app/config.py`](../app/config.py)
