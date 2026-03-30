#!/usr/bin/env bash
# VidSense — VM bootstrap script
#
# Run as root (or with sudo) on a fresh Ubuntu 24.04 LTS instance.
# Safe to re-run: all steps are idempotent.
#
# Usage:
#   sudo bash bootstrap.sh [--repo <git-url>] [--branch <branch>]
#
# Defaults:
#   --repo    https://github.com/grigory93/vidsense.git
#   --branch  main
#
# After this script:
#   1. Create /opt/vidsense/.env from .env.example and set real values.
#   2. Copy/edit /etc/caddy/Caddyfile for your domain.
#   3. sudo systemctl start vidsense && sudo systemctl reload caddy

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit these or pass as flags
# ---------------------------------------------------------------------------
REPO_URL="https://github.com/grigory93/vidsense.git"
BRANCH="main"
DEPLOY_DIR="/opt/vidsense"
SERVICE_USER="vidsense"

# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)   REPO_URL="$2";   shift 2 ;;
        --branch) BRANCH="$2";     shift 2 ;;
        *)        echo "Unknown flag: $1"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "[bootstrap] $*"; }
check_root() { [[ $EUID -eq 0 ]] || { echo "Run as root or with sudo."; exit 1; }; }

check_root

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
info "Updating apt..."
apt-get update -qq
apt-get upgrade -y -qq

info "Installing system dependencies..."
apt-get install -y -qq \
    git \
    curl \
    gnupg \
    apt-transport-https \
    ca-certificates \
    lsb-release

# Python: the project pins a micro version in .python-version and requires
# >= that in pyproject.toml. Ubuntu's stock python3.12 is often older (e.g.
# 3.12.3), so we install the matching CPython with uv after the repo is
# cloned — see "uv python install" below.

# ---------------------------------------------------------------------------
# 2. uv (Python package manager)
# ---------------------------------------------------------------------------
if ! command -v uv &>/dev/null; then
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
    if ! command -v uv &>/dev/null; then
        # Fallback: locate wherever the installer put it
        _uv_bin=$(find /root -name uv -type f 2>/dev/null | head -1)
        if [[ -n "${_uv_bin}" ]]; then
            cp "${_uv_bin}" /usr/local/bin/uv
        else
            echo "[bootstrap] ERROR: uv install succeeded but binary not found." >&2
            exit 1
        fi
    fi
else
    info "uv already installed, skipping."
fi

# Make sure uv is on PATH for subsequent steps
export PATH="/usr/local/bin:$PATH"

# ---------------------------------------------------------------------------
# 3. Caddy (official apt repository)
# ---------------------------------------------------------------------------
if ! command -v caddy &>/dev/null; then
    info "Installing Caddy..."
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
    apt-get install -y -qq caddy
else
    info "Caddy already installed, skipping."
fi

# Enable and start Caddy so it is ready for the final config reload
systemctl enable --now caddy

# ---------------------------------------------------------------------------
# 4. Service user
# ---------------------------------------------------------------------------
if ! id "${SERVICE_USER}" &>/dev/null; then
    info "Creating system user '${SERVICE_USER}'..."
    useradd --system --shell /usr/sbin/nologin --home-dir "${DEPLOY_DIR}" "${SERVICE_USER}"
else
    info "User '${SERVICE_USER}' already exists, skipping."
fi

# ---------------------------------------------------------------------------
# 5. Clone or update the repository
# ---------------------------------------------------------------------------
if [[ -d "${DEPLOY_DIR}/.git" ]]; then
    info "Repository already present at ${DEPLOY_DIR}, pulling latest..."
    sudo -u "${SERVICE_USER}" git -C "${DEPLOY_DIR}" fetch origin
    sudo -u "${SERVICE_USER}" git -C "${DEPLOY_DIR}" checkout "${BRANCH}"
    sudo -u "${SERVICE_USER}" git -C "${DEPLOY_DIR}" pull origin "${BRANCH}"
else
    info "Cloning repository to ${DEPLOY_DIR}..."
    git clone --branch "${BRANCH}" "${REPO_URL}" "${DEPLOY_DIR}"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${DEPLOY_DIR}"
fi

# Ensure ownership is correct after any operations
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${DEPLOY_DIR}"

# ---------------------------------------------------------------------------
# 6. Python interpreter (uv-managed) and project dependencies
# ---------------------------------------------------------------------------
PYTHON_SPEC_FILE="${DEPLOY_DIR}/.python-version"
if [[ -f "${PYTHON_SPEC_FILE}" ]]; then
    UV_PYTHON=$(tr -d '[:space:]' < "${PYTHON_SPEC_FILE}")
else
    UV_PYTHON="3.12"
fi
if [[ -z "${UV_PYTHON}" ]]; then
    UV_PYTHON="3.12"
fi

info "Installing CPython ${UV_PYTHON} via uv (matches .python-version / requires-python)..."
sudo -u "${SERVICE_USER}" \
    HOME="${DEPLOY_DIR}" \
    XDG_CACHE_HOME="${DEPLOY_DIR}/.cache" \
    uv python install "${UV_PYTHON}"

info "Installing Python dependencies via uv..."
sudo -u "${SERVICE_USER}" \
    HOME="${DEPLOY_DIR}" \
    XDG_CACHE_HOME="${DEPLOY_DIR}/.cache" \
    uv sync --project "${DEPLOY_DIR}" --python "${UV_PYTHON}"

# ---------------------------------------------------------------------------
# 7. Data directory
# ---------------------------------------------------------------------------
DATA_DIR="${DEPLOY_DIR}/data"
mkdir -p "${DATA_DIR}/embeddings"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${DATA_DIR}"
chmod 750 "${DATA_DIR}"

# ---------------------------------------------------------------------------
# 8. systemd unit
# ---------------------------------------------------------------------------
info "Installing systemd unit..."
cp "${DEPLOY_DIR}/deploy/vidsense.service" /etc/systemd/system/vidsense.service
systemctl daemon-reload
systemctl enable vidsense

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
cat <<EOF

[bootstrap] Setup complete.

Next steps (manual):

  1. Create /opt/vidsense/.env from the example and set real secrets:

       sudo -u vidsense cp /opt/vidsense/.env.example /opt/vidsense/.env
       sudo -u vidsense chmod 600 /opt/vidsense/.env
       sudo -u vidsense nano /opt/vidsense/.env   # set APP_SECRET_KEY, APP_ALLOWED_HOSTS, API keys, APP_DEBUG=false

  2. Configure Caddy for your domain:

       sudo cp /opt/vidsense/deploy/Caddyfile /etc/caddy/Caddyfile
       # Generate bcrypt hash: caddy hash-password --plaintext 'YourPassword'
       sudo nano /etc/caddy/Caddyfile   # replace YOUR_DOMAIN and add basicauth hash

  3. Start services:

       sudo systemctl start vidsense
       sudo systemctl status vidsense
       sudo journalctl -u vidsense -f   # watch for startup errors

       sudo systemctl status caddy
       sudo systemctl reload caddy
       sudo journalctl -u caddy -f      # watch for TLS cert issuance

  4. Smoke test:

       curl -u admin:YourPassword https://YOUR_DOMAIN

See docs/deployment-aws.md for the full AWS checklist.
EOF
