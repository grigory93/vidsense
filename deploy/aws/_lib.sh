#!/usr/bin/env bash
# VidSense — shared helpers for the AWS create/destroy/scan/backup scripts.
#
# Sourced by scan.sh, create.sh, destroy.sh, backup-vm.sh. Not executable on
# its own. Keeps config loading, the aws CLI wrapper, logging, and prompts in
# one place so the operational scripts stay small and consistent.

# Resolve the directory this library lives in, regardless of caller CWD.
AWS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY_DIR="${AWS_DIR}/inventory"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log()  { echo "[$(basename "${0}")] $*"; }
warn() { echo "[$(basename "${0}")] WARNING: $*" >&2; }
die()  { echo "[$(basename "${0}")] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Load deploy/aws/config.env if present. scan.sh can run without it (it probes
# every region); create/destroy require it and should call require_config.
load_config() {
    local cfg="${AWS_DIR}/config.env"
    if [[ -f "${cfg}" ]]; then
        # shellcheck disable=SC1090
        set -a; source "${cfg}"; set +a
        log "Loaded config from ${cfg}"
    fi
    # Export so the aws wrapper and child processes pick them up.
    # An empty AWS_PROFILE= in config.env would otherwise be exported by
    # `set -a` and make the CLI ignore the default SSO chain.
    if [[ -n "${AWS_PROFILE:-}" ]]; then
        export AWS_PROFILE
    else
        unset AWS_PROFILE
    fi
    [[ -n "${AWS_REGION:-}" ]] && export AWS_REGION
    PROJECT_TAG="${PROJECT_TAG:-vidsense}"
}

require_config() {
    local cfg="${AWS_DIR}/config.env"
    [[ -f "${cfg}" ]] || die "Missing ${cfg}. Copy config.example.env to config.env and fill it in."
    local var
    for var in "$@"; do
        [[ -n "${!var:-}" ]] || die "Required config value '${var}' is empty in ${cfg}."
    done
}

# ---------------------------------------------------------------------------
# AWS CLI
# ---------------------------------------------------------------------------
require_aws() {
    command -v aws >/dev/null 2>&1 || die "aws CLI not found. Install it: https://docs.aws.amazon.com/cli/"
    if ! aws sts get-caller-identity >/dev/null 2>&1; then
        die "AWS credentials are not usable. Run 'aws sso login' (or configure credentials) and retry."
    fi
}

# Thin wrapper so every call honors an optional region override as the first
# positional pair. Usage: awsr <region> <service> <op> [args...]
awsr() {
    local region="$1"; shift
    aws --region "${region}" "$@"
}

account_id() { aws sts get-caller-identity --query Account --output text; }

# Tag one or more EC2-family resource IDs with Project=<PROJECT_TAG>.
# Usage: tag_project <region> <id> [id...]
tag_project() {
    local region="$1"; shift
    [[ $# -gt 0 ]] || return 0
    awsr "${region}" ec2 create-tags --resources "$@" \
        --tags "Key=Project,Value=${PROJECT_TAG}"
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
# confirm "message" — returns 0 only if the user types exactly "yes".
confirm() {
    local prompt="${1:-Proceed?}"
    local answer
    read -r -p "${prompt} [type 'yes' to continue] " answer
    [[ "${answer}" == "yes" ]]
}

# ---------------------------------------------------------------------------
# Region enumeration
# ---------------------------------------------------------------------------
# Echo all opted-in / enabled regions, one per line. Falls back to a common set
# if the describe call is restricted.
all_regions() {
    aws ec2 describe-regions \
        --query 'Regions[].RegionName' --output text 2>/dev/null | tr '\t' '\n' | sort
}

# Read nonempty lines from stdin into a named array. Compatible with macOS
# /bin/bash 3.2, which does not have `mapfile`.
# Usage: read_lines_into DEST_ARRAY < <(some_command)
read_lines_into() {
    local dest="$1"
    local line
    eval "${dest}=()"
    while IFS= read -r line || [[ -n "${line}" ]]; do
        [[ -z "${line}" ]] && continue
        eval "${dest}+=(\"\$line\")"
    done
}
