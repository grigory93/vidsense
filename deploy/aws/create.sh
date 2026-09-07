#!/usr/bin/env bash
# VidSense — recreate the AWS infrastructure from deploy/aws/config.env.
#
# Idempotent: every resource is looked up by tag/name first and reused if it
# already exists, so re-running converges instead of duplicating. All resources
# are tagged Project=<PROJECT_TAG> so destroy.sh can find them later.
#
# What it creates (matching docs/deployment-aws.md):
#   1. Security group (SSH / HTTP / HTTPS inbound) in the default VPC
#   2. EC2 key pair — reuse KEY_PAIR_FILE if present; never overwrite it
#   3. Ubuntu 24.04 LTS instance with a gp3 root volume
#   4. Elastic IP, associated with the instance
#   5. (optional) Route 53 A record for DOMAIN -> Elastic IP
#
# It then waits for SSH and runs deploy/bootstrap.sh on the box. It does NOT
# create .env, Caddy basicauth, or restore data — do that with restore-vm.sh
# (see deploy/aws/README.md, "Recreate").
#
# Usage:
#   aws sso login
#   cp deploy/aws/config.example.env deploy/aws/config.env && $EDITOR ...
#   deploy/aws/create.sh

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

load_config
require_config AWS_REGION INSTANCE_NAME SECURITY_GROUP_NAME INSTANCE_TYPE \
    ROOT_VOLUME_SIZE_GB ROOT_VOLUME_TYPE AMI_NAME_PATTERN AMI_OWNER \
    KEY_PAIR_NAME KEY_PAIR_FILE SSH_INGRESS_CIDR REPO_URL REPO_BRANCH
require_aws

REGION="${AWS_REGION}"
KEY_PAIR_FILE="${KEY_PAIR_FILE/#\~/${HOME}}"

log "Target account $(account_id), region ${REGION}, tag Project=${PROJECT_TAG}."

# ---------------------------------------------------------------------------
# 1. Security group (default VPC — free; do not create a second VPC)
# ---------------------------------------------------------------------------
VPC_ID="$(awsr "${REGION}" ec2 describe-vpcs \
    --filters Name=isDefault,Values=true \
    --query 'Vpcs[0].VpcId' --output text)"
[[ "${VPC_ID}" != "None" && -n "${VPC_ID}" ]] || die "No default VPC in ${REGION}."
log "Using default VPC ${VPC_ID}."

SG_ID="$(awsr "${REGION}" ec2 describe-security-groups \
    --filters "Name=group-name,Values=${SECURITY_GROUP_NAME}" "Name=vpc-id,Values=${VPC_ID}" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")"

if [[ "${SG_ID}" == "None" || -z "${SG_ID}" ]]; then
    log "Creating security group ${SECURITY_GROUP_NAME}..."
    SG_ID="$(awsr "${REGION}" ec2 create-security-group \
        --group-name "${SECURITY_GROUP_NAME}" \
        --description "VidSense web VM (managed by deploy/aws/create.sh)" \
        --vpc-id "${VPC_ID}" \
        --tag-specifications "ResourceType=security-group,Tags=[{Key=Project,Value=${PROJECT_TAG}},{Key=Name,Value=${SECURITY_GROUP_NAME}}]" \
        --query 'GroupId' --output text)"
else
    log "Security group ${SECURITY_GROUP_NAME} already exists: ${SG_ID}."
    tag_project "${REGION}" "${SG_ID}"
fi

# Idempotently ensure inbound rules. Only a Duplicate error means the rule
# is already present; auth, CIDR, and API failures must abort create.
ensure_ingress() {
    local port="$1" cidr="$2" desc="$3" err
    if err="$(awsr "${REGION}" ec2 authorize-security-group-ingress \
        --group-id "${SG_ID}" \
        --ip-permissions "IpProtocol=tcp,FromPort=${port},ToPort=${port},IpRanges=[{CidrIp=${cidr},Description=${desc}}]" \
        2>&1)"; then
        log "  opened tcp/${port} from ${cidr}."
    elif [[ "${err}" == *InvalidPermission.Duplicate* ]]; then
        log "  tcp/${port} from ${cidr} already present — ok."
    else
        die "Failed to open tcp/${port} from ${cidr}: ${err}"
    fi
}
ensure_ingress 22 "${SSH_INGRESS_CIDR}" "SSH-admin-and-deploy"
ensure_ingress 80 "0.0.0.0/0" "HTTP-ACME"
ensure_ingress 443 "0.0.0.0/0" "HTTPS-public"

# ---------------------------------------------------------------------------
# 2. Key pair
# ---------------------------------------------------------------------------
# Prefer the existing local private key (e.g. ~/.ssh/vidsensed-dev.pem, the
# IdentityFile in ~/.ssh/config Host vidsense-dev). Never overwrite it.
# destroy.sh does not delete the AWS key pair; if it is gone anyway, re-import
# the public half so the same .pem still logs you in after recreate.
if [[ -f "${KEY_PAIR_FILE}" ]]; then
    log "Using existing local key ${KEY_PAIR_FILE} (will not overwrite)."
    PUB_TMP="$(mktemp)"
    ssh-keygen -y -f "${KEY_PAIR_FILE}" > "${PUB_TMP}" \
        || { rm -f "${PUB_TMP}"; die "Could not read public key from ${KEY_PAIR_FILE}."; }
    if awsr "${REGION}" ec2 describe-key-pairs --key-names "${KEY_PAIR_NAME}" >/dev/null 2>&1; then
        log "AWS already has key pair ${KEY_PAIR_NAME}; attaching it to the new instance."
    else
        log "AWS is missing ${KEY_PAIR_NAME}; importing the public key from ${KEY_PAIR_FILE}..."
        awsr "${REGION}" ec2 import-key-pair \
            --key-name "${KEY_PAIR_NAME}" \
            --public-key-material "fileb://${PUB_TMP}" \
            --tag-specifications "ResourceType=key-pair,Tags=[{Key=Project,Value=${PROJECT_TAG}}]" \
            >/dev/null
        log "  imported. The same IdentityFile still works."
    fi
    rm -f "${PUB_TMP}"
elif awsr "${REGION}" ec2 describe-key-pairs --key-names "${KEY_PAIR_NAME}" >/dev/null 2>&1; then
    die "Key pair ${KEY_PAIR_NAME} exists in AWS but ${KEY_PAIR_FILE} is missing locally. Restore the original .pem (do not create a new pair) and retry."
else
    log "No local key and no AWS key pair — creating ${KEY_PAIR_NAME} -> ${KEY_PAIR_FILE}..."
    mkdir -p "$(dirname "${KEY_PAIR_FILE}")"
    awsr "${REGION}" ec2 create-key-pair --key-name "${KEY_PAIR_NAME}" \
        --tag-specifications "ResourceType=key-pair,Tags=[{Key=Project,Value=${PROJECT_TAG}}]" \
        --query 'KeyMaterial' --output text > "${KEY_PAIR_FILE}"
    chmod 400 "${KEY_PAIR_FILE}"
    log "  private key written to ${KEY_PAIR_FILE} (chmod 400). Back it up."
fi

# ---------------------------------------------------------------------------
# 3. EC2 instance (reuse a running/stopped instance if present)
# ---------------------------------------------------------------------------
# A reused stopped/stopping instance must be started before SSH/bootstrap.
# start-instances is rejected while the instance is still stopping, so wait
# for stopped first in that case.
ensure_instance_running() {
    local instance_id="$1"
    local state
    state="$(awsr "${REGION}" ec2 describe-instances \
        --instance-ids "${instance_id}" \
        --query 'Reservations[0].Instances[0].State.Name' --output text)"
    case "${state}" in
        running)
            log "  instance ${instance_id} already running."
            return 0
            ;;
        pending)
            ;;
        stopping)
            log "  instance ${instance_id} is stopping; waiting until stopped..."
            awsr "${REGION}" ec2 wait instance-stopped --instance-ids "${instance_id}"
            state="stopped"
            ;;
        stopped)
            ;;
        *)
            die "Instance ${instance_id} is in state '${state}'; cannot reuse."
            ;;
    esac
    if [[ "${state}" == "stopped" ]]; then
        log "  instance ${instance_id} is stopped; starting..."
        awsr "${REGION}" ec2 start-instances --instance-ids "${instance_id}" >/dev/null
    fi
    log "  instance ${instance_id} waiting until running..."
    awsr "${REGION}" ec2 wait instance-running --instance-ids "${instance_id}"
}

# Prefer Project+Name (what this script creates). Fall back to Name alone so
# a console-launched VM (the current live box has no Project tag) is reused
# instead of launching a second instance.
INSTANCE_ID="$(awsr "${REGION}" ec2 describe-instances \
    --filters "Name=tag:Project,Values=${PROJECT_TAG}" \
              "Name=tag:Name,Values=${INSTANCE_NAME}" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || echo "None")"

if [[ "${INSTANCE_ID}" == "None" || -z "${INSTANCE_ID}" ]]; then
    INSTANCE_ID="$(awsr "${REGION}" ec2 describe-instances \
        --filters "Name=tag:Name,Values=${INSTANCE_NAME}" \
                  "Name=instance-state-name,Values=pending,running,stopping,stopped" \
        --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || echo "None")"
    if [[ "${INSTANCE_ID}" != "None" && -n "${INSTANCE_ID}" ]]; then
        log "Found untagged instance ${INSTANCE_ID} by Name=${INSTANCE_NAME}; tagging Project=${PROJECT_TAG}."
        tag_project "${REGION}" "${INSTANCE_ID}"
    fi
fi

if [[ "${INSTANCE_ID}" != "None" && -n "${INSTANCE_ID}" ]]; then
    log "Reusing existing instance ${INSTANCE_ID} (${INSTANCE_NAME})."
    ensure_instance_running "${INSTANCE_ID}"
else
    log "Looking up latest Ubuntu AMI (${AMI_NAME_PATTERN})..."
    AMI_ID="$(awsr "${REGION}" ec2 describe-images \
        --owners "${AMI_OWNER}" \
        --filters "Name=name,Values=${AMI_NAME_PATTERN}" \
                  "Name=state,Values=available" \
                  "Name=architecture,Values=x86_64" \
        --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)"
    [[ "${AMI_ID}" != "None" && -n "${AMI_ID}" ]] || die "No AMI matched ${AMI_NAME_PATTERN} for owner ${AMI_OWNER}."
    log "  AMI: ${AMI_ID}"

    log "Launching ${INSTANCE_TYPE} instance..."
    INSTANCE_ID="$(awsr "${REGION}" ec2 run-instances \
        --image-id "${AMI_ID}" \
        --instance-type "${INSTANCE_TYPE}" \
        --key-name "${KEY_PAIR_NAME}" \
        --security-group-ids "${SG_ID}" \
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=${ROOT_VOLUME_SIZE_GB},VolumeType=${ROOT_VOLUME_TYPE},DeleteOnTermination=true}" \
        --tag-specifications \
            "ResourceType=instance,Tags=[{Key=Project,Value=${PROJECT_TAG}},{Key=Name,Value=${INSTANCE_NAME}}]" \
            "ResourceType=volume,Tags=[{Key=Project,Value=${PROJECT_TAG}},{Key=Name,Value=${INSTANCE_NAME}-root}]" \
        --query 'Instances[0].InstanceId' --output text)"
    log "  instance ${INSTANCE_ID} launching; waiting until running..."
    awsr "${REGION}" ec2 wait instance-running --instance-ids "${INSTANCE_ID}"
fi

# ---------------------------------------------------------------------------
# 4. Elastic IP
# ---------------------------------------------------------------------------
# Reuse a tagged EIP, or the one already on this instance (console-launched
# VMs have an untagged EIP). Never allocate a second address onto a live box.
ALLOC_ID="$(awsr "${REGION}" ec2 describe-addresses \
    --filters "Name=tag:Project,Values=${PROJECT_TAG}" \
    --query 'Addresses[0].AllocationId' --output text 2>/dev/null || echo "None")"

if [[ "${ALLOC_ID}" == "None" || -z "${ALLOC_ID}" ]]; then
    ALLOC_ID="$(awsr "${REGION}" ec2 describe-addresses \
        --filters "Name=instance-id,Values=${INSTANCE_ID}" \
        --query 'Addresses[0].AllocationId' --output text 2>/dev/null || echo "None")"
    if [[ "${ALLOC_ID}" != "None" && -n "${ALLOC_ID}" ]]; then
        log "Found untagged Elastic IP on ${INSTANCE_ID}; tagging Project=${PROJECT_TAG}."
        tag_project "${REGION}" "${ALLOC_ID}"
    fi
fi

if [[ "${ALLOC_ID}" == "None" || -z "${ALLOC_ID}" ]]; then
    log "Allocating Elastic IP..."
    ALLOC_ID="$(awsr "${REGION}" ec2 allocate-address --domain vpc \
        --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Project,Value=${PROJECT_TAG}},{Key=Name,Value=${INSTANCE_NAME}}]" \
        --query 'AllocationId' --output text)"
else
    log "Reusing Elastic IP allocation ${ALLOC_ID}."
fi

ATTACHED_INSTANCE="$(awsr "${REGION}" ec2 describe-addresses \
    --allocation-ids "${ALLOC_ID}" \
    --query 'Addresses[0].InstanceId' --output text 2>/dev/null || echo "None")"
if [[ "${ATTACHED_INSTANCE}" == "${INSTANCE_ID}" ]]; then
    log "Elastic IP already associated with ${INSTANCE_ID}."
else
    log "Associating Elastic IP with ${INSTANCE_ID}..."
    awsr "${REGION}" ec2 associate-address \
        --instance-id "${INSTANCE_ID}" --allocation-id "${ALLOC_ID}" >/dev/null
fi

PUBLIC_IP="$(awsr "${REGION}" ec2 describe-addresses \
    --allocation-ids "${ALLOC_ID}" --query 'Addresses[0].PublicIp' --output text)"
log "Public IP: ${PUBLIC_IP}"

# ---------------------------------------------------------------------------
# 5. Route 53 (optional)
# ---------------------------------------------------------------------------
if [[ -n "${ROUTE53_ZONE_ID:-}" && -n "${DOMAIN:-}" ]]; then
    log "Upserting Route 53 A records -> ${PUBLIC_IP} (zone ${ROUTE53_ZONE_ID})..."
    for rec in ${DOMAIN} ${EXTRA_A_RECORDS:-}; do
        log "  ${rec}"
        CHANGE_BATCH="$(cat <<JSON
{"Changes":[{"Action":"UPSERT","ResourceRecordSet":{"Name":"${rec}","Type":"A","TTL":300,"ResourceRecords":[{"Value":"${PUBLIC_IP}"}]}}]}
JSON
)"
        aws route53 change-resource-record-sets \
            --hosted-zone-id "${ROUTE53_ZONE_ID}" \
            --change-batch "${CHANGE_BATCH}" >/dev/null
    done
    log "  DNS updated (propagation up to TTL=300s)."
else
    warn "ROUTE53_ZONE_ID or DOMAIN not set — skipping DNS. Point ${DOMAIN:-your domain} at ${PUBLIC_IP} manually."
fi

# ---------------------------------------------------------------------------
# 6. Bootstrap the VM
# ---------------------------------------------------------------------------
LOGIN_USER="${AMI_LOGIN_USER:-ubuntu}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -i "${KEY_PAIR_FILE}")

log "Waiting for SSH on ${PUBLIC_IP} (as ${LOGIN_USER})..."
for _ in $(seq 1 30); do
    if ssh "${SSH_OPTS[@]}" "${LOGIN_USER}@${PUBLIC_IP}" "echo ok" >/dev/null 2>&1; then
        break
    fi
    sleep 10
done
ssh "${SSH_OPTS[@]}" "${LOGIN_USER}@${PUBLIC_IP}" "echo ok" >/dev/null 2>&1 \
    || die "SSH never came up on ${PUBLIC_IP}. Check the security group SSH CIDR (${SSH_INGRESS_CIDR}) and your IP."

REPO_ROOT="$(cd "${AWS_DIR}/../.." && pwd)"
log "Copying deploy/bootstrap.sh to the VM..."
scp "${SSH_OPTS[@]}" "${REPO_ROOT}/deploy/bootstrap.sh" "${LOGIN_USER}@${PUBLIC_IP}:/tmp/bootstrap.sh"

log "Running bootstrap.sh (repo ${REPO_URL}, branch ${REPO_BRANCH})..."
ssh "${SSH_OPTS[@]}" "${LOGIN_USER}@${PUBLIC_IP}" \
    "chmod +x /tmp/bootstrap.sh && sudo /tmp/bootstrap.sh --repo '${REPO_URL}' --branch '${REPO_BRANCH}'"

cat <<EOF

[create] Infrastructure is up.

  Instance:   ${INSTANCE_ID}
  Public IP:  ${PUBLIC_IP}
  SSH:        ssh -i ${KEY_PAIR_FILE} ${LOGIN_USER}@${PUBLIC_IP}
              (or: ssh vidsense-dev after you set HostName ${PUBLIC_IP}
               in ~/.ssh/config — IdentityFile stays ${KEY_PAIR_FILE})

Remaining MANUAL steps (see deploy/aws/README.md, "Recreate"):
  1. Restore state from the freeze backup (preferred):
       deploy/aws/restore-vm.sh --start <backup.tar.gz> ${PUBLIC_IP}
     Or create a fresh /opt/vidsense/.env and Caddyfile (APP_SECRET_KEY,
     YOUTUBE_API_KEY, LLM keys, APP_ALLOWED_HOSTS=${DOMAIN:-your-domain},
     WEBSHARE_PROXY_*).
  2. Smoke test https://${DOMAIN:-<domain>}.
  3. Update GitHub deploy secrets: SSH_HOST=${PUBLIC_IP} (or ${DOMAIN:-domain}),
     SSH_USER=${SERVICE_USER:-vidsense}, add the deploy public key to the VM.
  4. Re-enable the deploy workflow push trigger.
EOF
