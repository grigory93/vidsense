#!/usr/bin/env bash
# VidSense — restore a backup-vm.sh archive onto a freshly created VM.
#
# Inverse of backup-vm.sh. The outer archive contains:
#   payload.tar.gz  — opt/vidsense/data, opt/vidsense/.env, etc/caddy/Caddyfile
#   known_hosts     — ssh-keyscan of the OLD host (informational; new VM has
#                     new host keys)
#
# Run AFTER create.sh (bootstrap must have created the vidsense user and
# /opt/vidsense). Does not start services unless you pass --start.
#
# Usage:
#   deploy/aws/restore-vm.sh [--start] [archive] [ssh-host] [ssh-user] [ssh-key]
#
#   --start   Reload Caddy and start systemd vidsense after restoring files.
#   archive   Defaults to the newest deploy/aws/backups/vidsense-vm-*.tar.gz
#   ssh-host  Defaults to DOMAIN (vidsense.info). Prefer the new Elastic IP
#             printed by create.sh — DNS TTL is 300s.
#   ssh-user  Defaults to AMI_LOGIN_USER (ubuntu)
#   ssh-key   Defaults to KEY_PAIR_FILE (~/.ssh/vidsensed-dev.pem)

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

START=0
if [[ "${1:-}" == "--start" ]]; then
    START=1
    shift
fi

load_config

BACKUP_DIR="${AWS_DIR}/backups"
if [[ -n "${1:-}" ]]; then
    ARCHIVE="$1"
    shift
else
    ARCHIVE="$(ls -1t "${BACKUP_DIR}"/vidsense-vm-*.tar.gz 2>/dev/null | head -1 || true)"
fi
[[ -n "${ARCHIVE}" && -f "${ARCHIVE}" ]] \
    || die "No backup archive found. Pass a path or put one in ${BACKUP_DIR}/."

SSH_HOST="${1:-${DOMAIN:-}}"
[[ -n "${SSH_HOST}" ]] || die "Usage: restore-vm.sh [--start] [archive] [ssh-host] [ssh-user] [ssh-key]"
SSH_USER="${2:-${AMI_LOGIN_USER:-ubuntu}}"
SSH_KEY="${3:-${KEY_PAIR_FILE:-}}"
SSH_KEY="${SSH_KEY/#\~/${HOME}}"
[[ -n "${SSH_KEY}" && -f "${SSH_KEY}" ]] || die "SSH key not found: ${SSH_KEY:-<empty>}"

# New VMs have new host keys. Drop any stale known_hosts entry for this host
# (old EIP or vidsense.info) and accept the new one.
ssh-keygen -R "${SSH_HOST}" >/dev/null 2>&1 || true
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -i "${SSH_KEY}")

STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

log "Unpacking outer archive ${ARCHIVE}..."
tar xzf "${ARCHIVE}" -C "${STAGE}"
[[ -f "${STAGE}/payload.tar.gz" ]] \
    || die "Archive is missing payload.tar.gz (is this a backup-vm.sh output?)"

CONTENTS="$(tar tzf "${STAGE}/payload.tar.gz")"
echo "${CONTENTS}" | grep -qx 'opt/vidsense/.env' \
    || die "payload.tar.gz is missing opt/vidsense/.env"
echo "${CONTENTS}" | grep -q '^opt/vidsense/data/' \
    || die "payload.tar.gz is missing opt/vidsense/data/"
echo "${CONTENTS}" | grep -qx 'etc/caddy/Caddyfile' \
    || die "payload.tar.gz is missing etc/caddy/Caddyfile"

remote() { ssh "${SSH_OPTS[@]}" "${SSH_USER}@${SSH_HOST}" "$@"; }

log "Connecting to ${SSH_USER}@${SSH_HOST}..."
remote "echo connected" >/dev/null \
    || die "Cannot SSH to ${SSH_USER}@${SSH_HOST}. Use the new Elastic IP from create.sh."

remote "id vidsense >/dev/null" \
    || die "User 'vidsense' is missing — run create.sh (bootstrap) before restore."
remote "sudo test -d /opt/vidsense" \
    || die "/opt/vidsense is missing — run create.sh (bootstrap) before restore."

log "Uploading payload..."
scp "${SSH_OPTS[@]}" "${STAGE}/payload.tar.gz" "${SSH_USER}@${SSH_HOST}:/tmp/vidsense-restore.tar.gz"

log "Extracting onto the VM (data, .env, Caddyfile)..."
remote "sudo tar xzf /tmp/vidsense-restore.tar.gz -C / \
    && sudo chown -R vidsense:vidsense /opt/vidsense \
    && sudo chmod 600 /opt/vidsense/.env \
    && sudo rm -f /tmp/vidsense-restore.tar.gz"

log "Restored .env keys (values not printed):"
remote "sudo grep -E '^[A-Za-z_][A-Za-z0-9_]*=' /opt/vidsense/.env | sed 's/=.*$//' | sed 's/^/  /'"

if remote "sudo grep -qE '^[[:space:]]*WEBSHARE_PROXY_USERNAME=.+' /opt/vidsense/.env" \
    && remote "sudo grep -qE '^[[:space:]]*WEBSHARE_PROXY_PASSWORD=.+' /opt/vidsense/.env"; then
    log "Webshare proxy credentials ARE present on the restored .env."
else
    warn "WEBSHARE_PROXY_USERNAME and/or WEBSHARE_PROXY_PASSWORD are missing."
    warn "Transcript fetches from this EC2 will be blocked by YouTube until you add them."
fi

if [[ ${START} -eq 1 ]]; then
    log "Reloading Caddy and starting vidsense..."
    remote "sudo systemctl reload caddy && sudo systemctl start vidsense"
    remote "sudo systemctl --no-pager --full is-active caddy vidsense" || \
        warn "A service is not active. Check: sudo journalctl -u vidsense -u caddy -e"
else
    echo ""
    echo "Files restored. Start the app when ready:"
    echo "  ssh -i ${SSH_KEY} ${SSH_USER}@${SSH_HOST} 'sudo systemctl reload caddy && sudo systemctl start vidsense'"
fi

log "Restore complete."
echo ""
echo "Smoke test (once DNS / Caddy TLS is up):"
echo "  curl -I http://${DOMAIN:-${SSH_HOST}}"
echo "  curl -u admin:<caddy-password> https://${DOMAIN:-${SSH_HOST}}"
