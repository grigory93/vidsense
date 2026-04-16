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

# systemctl restart blocks until the unit reaches an active state or fails,
# but double-check explicitly so a subtle unit failure can't be confused
# with a successful deploy.
if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "[update] ERROR: ${SERVICE_NAME} is not active after restart." >&2
    systemctl status "${SERVICE_NAME}" --no-pager | head -n 40 >&2 || true
    exit 1
fi

systemctl status "${SERVICE_NAME}" --no-pager | head -n 20

log "Deploy of ${BRANCH} complete at $(git rev-parse --short HEAD)."
