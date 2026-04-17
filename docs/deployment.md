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

## Transcript fetching on cloud VMs

YouTube blocks transcript requests from cloud-datacenter IP ranges (AWS, GCP, Azure, DigitalOcean, Hetzner, etc.). The metadata and comments APIs (authenticated with `YOUTUBE_API_KEY`) are unaffected — only the unauthenticated transcript endpoint is blocked. The fix is to route transcript requests through a residential proxy. **This is not needed for local development.**

### Which Webshare plan to buy

`youtube-transcript-api`'s built-in `WebshareProxyConfig` is designed for Webshare's **Residential** (rotating) proxy product. The free tier and the "Proxy Server" / "Static Residential" plans use datacenter IPs and will still be blocked by YouTube. Pricing starts around $3–6/month for the smallest residential tier. Sign up at [webshare.io](https://www.webshare.io/).

### Where to find the credentials

In the Webshare dashboard, navigate to **Proxy → Proxy Settings** (or **Residential → Settings**). Webshare issues a dedicated **Proxy Username** and **Proxy Password** per subaccount — these are *not* your Webshare login email and password. Copy both values verbatim.

### What to put in `.env`

Exactly two variables:

```bash
WEBSHARE_PROXY_USERNAME=<from Webshare dashboard>
WEBSHARE_PROXY_PASSWORD=<from Webshare dashboard>
```

Endpoint defaults (`p.webshare.io:80`, rotation enabled) are applied automatically by `WebshareProxyConfig`. Do not override `domain_name` or `proxy_port` — doing so can silently route traffic through the wrong Webshare product.

The app validates at startup that either both or neither of the two vars are set. Setting exactly one triggers a clear error.

### Optional tuning (not wired, but the knobs exist)

If you later want to constrain exit countries (some YouTube videos are geo-restricted) or tune retries, `WebshareProxyConfig` also accepts `filter_ip_locations=["US", "CA", "GB"]` and `retries_when_blocked=N` (default 10). Adding these is a one-line change in [`app/services/youtube.py`](../app/services/youtube.py).

### How to verify before restart

From the VM, confirm the proxy works independently of the app:

```bash
export WEBSHARE_PROXY_USERNAME='<from Webshare dashboard>'
export WEBSHARE_PROXY_PASSWORD='<from Webshare dashboard>'
curl --proxy-user "${WEBSHARE_PROXY_USERNAME}-rotate:${WEBSHARE_PROXY_PASSWORD}" \
  -x http://p.webshare.io:80 \
  https://api.ipify.org
```

A successful response prints a residential-looking IP that is *not* the VM's own IP. If `curl` hangs, returns a 407, or prints the VM's IP, the credentials or plan type are wrong — fix that before restarting the service.

## Deployment files

| File | Purpose |
|------|---------|
| [`deploy/Caddyfile`](../deploy/Caddyfile) | TLS, basicauth, security headers, CSP, request-size limit, reverse proxy to `127.0.0.1:8000` |
| [`deploy/vidsense.service`](../deploy/vidsense.service) | systemd unit: non-root user, restart policy, hardening options |
| [`deploy/bootstrap.sh`](../deploy/bootstrap.sh) | Idempotent VM setup script (Ubuntu): uv, Caddy, clone repo, `uv python install` + `uv sync`, service user |

## Related

- Environment template and production hints: [`.env.example`](../.env.example)
- Application settings: [`app/config.py`](../app/config.py)
