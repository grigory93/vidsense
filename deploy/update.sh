#!/usr/bin/env bash
# VidSense — on-VM deploy script.
#
# Invoked by the GitHub Actions deploy workflow via SSH as the `vidsense`
# service user:
#
#     ssh vidsense@<host> bash /opt/vidsense/deploy/update.sh [branch]
#
# The script is safe to re-run. It fails loudly if any step breaks so
# partial deploys show up as red builds instead of silent drift.
#
# Prerequisites (installed by deploy/bootstrap.sh):
#   - /opt/vidsense is a git checkout of the project.
#   - The vidsense service user has /bin/bash as its login shell.
#   - /etc/sudoers.d/vidsense grants:
#       vidsense ALL=(root) NOPASSWD: /bin/systemctl restart vidsense
#   - uv is on PATH at /usr/local/bin/uv.

set -euo pipefail

# Explicit environment: SSH non-interactive sessions inherit a minimal env,
# and uv needs HOME/XDG pointed at the service user's directory so caches
# and configs land where bootstrap.sh expects them.
export PATH="/usr/local/bin:/usr/bin:/bin"
export HOME="/opt/vidsense"
export XDG_CONFIG_HOME="${HOME}/.config"
export XDG_CACHE_HOME="${HOME}/.cache"

DEPLOY_DIR="/opt/vidsense"
SERVICE_NAME="vidsense"
BRANCH="${1:-main}"

log() { echo "[update] $*"; }

if [[ ! -d "${DEPLOY_DIR}/.git" ]]; then
    echo "[update] ERROR: ${DEPLOY_DIR} is not a git checkout." >&2
    exit 1
fi

cd "${DEPLOY_DIR}"

log "Fetching origin..."
git fetch --prune origin

log "Checking out ${BRANCH}..."
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

log "Syncing dependencies (uv sync --frozen)..."
uv sync --frozen

log "Restarting ${SERVICE_NAME}..."
sudo /bin/systemctl restart "${SERVICE_NAME}"

# vidsense.service is Type=simple, so `systemctl restart` returns as soon as
# the uvicorn process is forked — long before it has imported main:app, run
# its lifespan hook, or bound :8000. That makes `is-active` a near-no-op for
# the most common deploy-time failures (import errors, missing APP_SECRET_KEY,
# invalid YOUTUBE_API_KEY, etc.), because Restart=on-failure keeps the unit
# flipping between "activating" and "active" during a crash loop.
#
# The real readiness signal is an HTTP response on the listen port: any status
# code from 100–599 proves uvicorn imported the app and bound the socket.
# Require several consecutive successes so a service that briefly answers
# before crashing can't masquerade as healthy.
HEALTH_URL="http://127.0.0.1:8000/"
HEALTH_TIMEOUT=30
REQUIRED_SUCCESSES=3

log "Probing ${HEALTH_URL} for ${REQUIRED_SUCCESSES} consecutive successes (timeout ${HEALTH_TIMEOUT}s)..."
deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
consecutive=0
last_status="000"
while (( $(date +%s) < deadline )); do
    # curl writes "%{http_code}" (e.g. "000" on connect failure, "200" on a
    # successful header exchange that then times out on the body) to stdout
    # *before* exiting non-zero. Using `|| true` preserves that value;
    # `|| echo "000"` would append and give us e.g. "000000" or "200000",
    # which fails the regex below and causes false-negative health checks.
    last_status=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 2 "${HEALTH_URL}" || true)
    if [[ "${last_status}" =~ ^[1-5][0-9][0-9]$ ]]; then
        consecutive=$(( consecutive + 1 ))
        if (( consecutive >= REQUIRED_SUCCESSES )); then
            break
        fi
    else
        consecutive=0
    fi
    sleep 1
done

if (( consecutive < REQUIRED_SUCCESSES )); then
    echo "[update] ERROR: ${SERVICE_NAME} did not stay healthy on ${HEALTH_URL} within ${HEALTH_TIMEOUT}s (last HTTP status: ${last_status})." >&2
    # `systemctl status` shows the current unit state (e.g. "active (running)"
    # during a crash loop where Restart=on-failure keeps respawning uvicorn).
    # That's nearly useless for diagnosis — the actual Python traceback is in
    # the journal. Dump both so the GitHub Actions log surfaces the root cause
    # without requiring an SSH round-trip.
    systemctl status "${SERVICE_NAME}" --no-pager | head -n 40 >&2 || true
    echo "[update] Last ${SERVICE_NAME} journal lines:" >&2
    journalctl -u "${SERVICE_NAME}" -n 80 --no-pager >&2 || true
    exit 1
fi

log "${SERVICE_NAME} is serving (HTTP ${last_status})."
# `|| true` guards against SIGPIPE (exit 141) when `head` closes its stdin
# before `systemctl status` finishes writing — under `set -euo pipefail`
# that would abort an otherwise-successful deploy.
systemctl status "${SERVICE_NAME}" --no-pager | head -n 20 || true

log "Deploy of ${BRANCH} complete at $(git rev-parse --short HEAD)."
