#!/usr/bin/env bash
# VidSense — pull irreplaceable state off the VM before destroy.
#
# The VM disk holds everything that is NOT in git: the SQLite database, FAISS
# embedding indexes, the production .env (all secrets, including Webshare),
# and the Caddy config (domain + basicauth hash). destroy.sh deletes the
# instance and its volume, so run this FIRST and store the tarball somewhere
# safe (outside git).
#
# SSH as the AMI login user (ubuntu), not the vidsense service user. The
# EC2 key pair (vidsensed-dev.pem) is authorized for ubuntu; ubuntu has
# passwordless sudo. The vidsense user only has sudo for systemctl restart.
#
# Usage:
#   deploy/aws/backup-vm.sh [ssh-host] [ssh-user] [ssh-key]
#
#   ssh-host  Defaults to DOMAIN (vidsense.info). Also accepts the EIP or
#             an ~/.ssh/config Host alias (vidsense-dev).
#   ssh-user  Defaults to AMI_LOGIN_USER (ubuntu)
#   ssh-key   Defaults to KEY_PAIR_FILE (~/.ssh/vidsensed-dev.pem)
#
# Produces: deploy/aws/backups/vidsense-vm-<timestamp>.tar.gz (gitignored)

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

load_config

SSH_HOST="${1:-${DOMAIN:-}}"
[[ -n "${SSH_HOST}" ]] || die "Usage: backup-vm.sh [ssh-host] [ssh-user] [ssh-key]"
SSH_USER="${2:-${AMI_LOGIN_USER:-ubuntu}}"
SSH_KEY="${3:-${KEY_PAIR_FILE:-}}"
SSH_KEY="${SSH_KEY/#\~/${HOME}}"
[[ -n "${SSH_KEY}" && -f "${SSH_KEY}" ]] || die "SSH key not found: ${SSH_KEY:-<empty>}"

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -i "${SSH_KEY}")

BACKUP_DIR="${AWS_DIR}/backups"
mkdir -p "${BACKUP_DIR}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

remote() { ssh "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}" "$@"; }

log "Backing up ${SSH_USER}@${SSH_HOST} (key: ${SSH_KEY})..."
remote "echo connected" >/dev/null || die "Cannot SSH to ${SSH_USER}@${SSH_HOST}. Check host/user/key and security group."

log "Checking that required paths exist on the VM..."
remote "sudo test -d /opt/vidsense/data" \
    || die "/opt/vidsense/data missing on the VM."
remote "sudo test -f /opt/vidsense/.env" \
    || die "/opt/vidsense/.env missing on the VM — production secrets (including Webshare) would be lost."
remote "sudo test -f /etc/caddy/Caddyfile" \
    || die "/etc/caddy/Caddyfile missing on the VM."

log "Archiving /opt/vidsense/data, /opt/vidsense/.env, /etc/caddy/Caddyfile..."
remote "sudo tar czf /tmp/vidsense-backup.tar.gz -C / \
    opt/vidsense/data \
    opt/vidsense/.env \
    etc/caddy/Caddyfile \
    && sudo chmod 644 /tmp/vidsense-backup.tar.gz"

log "Downloading tarball..."
scp "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}:/tmp/vidsense-backup.tar.gz" "${STAGE}/payload.tar.gz"
remote "sudo rm -f /tmp/vidsense-backup.tar.gz" || true

log "Verifying archive contents..."
CONTENTS="$(tar tzf "${STAGE}/payload.tar.gz")"
echo "${CONTENTS}" | grep -qx 'opt/vidsense/.env' \
    || die "Backup is missing opt/vidsense/.env"
echo "${CONTENTS}" | grep -q '^opt/vidsense/data/' \
    || die "Backup is missing opt/vidsense/data/"
echo "${CONTENTS}" | grep -qx 'etc/caddy/Caddyfile' \
    || die "Backup is missing etc/caddy/Caddyfile"

# Report whether Webshare (and other required) vars are present — values masked.
log "Production .env keys present (values not printed):"
tar xzf "${STAGE}/payload.tar.gz" -O opt/vidsense/.env \
    | grep -E '^[A-Za-z_][A-Za-z0-9_]*=' \
    | sed 's/=.*$//' \
    | while IFS= read -r key; do
        echo "  ${key}"
      done

if tar xzf "${STAGE}/payload.tar.gz" -O opt/vidsense/.env \
    | grep -qE '^[[:space:]]*WEBSHARE_PROXY_USERNAME=.+' \
    && tar xzf "${STAGE}/payload.tar.gz" -O opt/vidsense/.env \
    | grep -qE '^[[:space:]]*WEBSHARE_PROXY_PASSWORD=.+'; then
    log "Webshare proxy credentials ARE set on the VM .env (needed after recreate)."
else
    warn "WEBSHARE_PROXY_USERNAME and/or WEBSHARE_PROXY_PASSWORD are missing on the VM .env."
    warn "Transcript fetches from the new EC2 will be blocked by YouTube until you add them."
fi

log "Capturing SSH host keys (ssh-keyscan)..."
ssh-keyscan -H "${SSH_HOST}" > "${STAGE}/known_hosts" 2>/dev/null || \
    warn "ssh-keyscan failed; SSH_KNOWN_HOSTS not captured."

OUT="${BACKUP_DIR}/vidsense-vm-${TIMESTAMP}.tar.gz"
tar czf "${OUT}" -C "${STAGE}" .
CHECKSUM="$(shasum -a 256 "${OUT}" | awk '{print $1}')"

log "Backup complete."
log "File:   ${OUT}"
log "SHA256: ${CHECKSUM}"
echo ""
echo "IMPORTANT: copy this file somewhere durable OUTSIDE this repo (it contains"
echo "your production .env and Caddy password hash). It is gitignored on purpose."
echo ""
echo "Outer archive:"
tar tzf "${OUT}" | sed 's/^/  /'
echo "Inner payload:"
echo "${CONTENTS}" | sed 's/^/  /'
