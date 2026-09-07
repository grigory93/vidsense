#!/usr/bin/env bash
# VidSense — tear down the AWS infrastructure created by create.sh.
#
# Deletes ONLY resources tagged Project=<PROJECT_TAG> in AWS_REGION, in a safe
# order, so you stop paying while the site is frozen. It prints exactly what it
# will delete and requires you to type 'yes' before doing anything.
#
# Order: disassociate + release Elastic IP -> terminate instance (its root
# volume has DeleteOnTermination=true) -> delete security group.
# The account default VPC is left in place (it is free).
#
# By DEFAULT it leaves the Route 53 hosted zone alone (a hosted zone is ~$0.50
# per month and keeps your DNS/domain intact). Pass --delete-dns to also remove
# the A record for DOMAIN (the zone itself is never deleted by this script).
#
# ALWAYS run backup-vm.sh first — terminating the instance destroys the SQLite
# DB, FAISS indexes, .env, and Caddy config permanently.
#
# Usage:
#   deploy/aws/backup-vm.sh <host>        # FIRST — save the data
#   deploy/aws/destroy.sh                 # tear down compute + network
#   deploy/aws/destroy.sh --delete-dns    # also remove the DOMAIN A record

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

DELETE_DNS=0
[[ "${1:-}" == "--delete-dns" ]] && DELETE_DNS=1

load_config
require_config AWS_REGION
require_aws

REGION="${AWS_REGION}"
log "Account $(account_id), region ${REGION}, selecting resources tagged Project=${PROJECT_TAG}."

# ---------------------------------------------------------------------------
# Discover resources: Project tag (create.sh) AND live names from config
# (the current VM was launched from the console and is not tagged).
# ---------------------------------------------------------------------------
read_lines_into INSTANCE_IDS < <(
    {
        awsr "${REGION}" ec2 describe-instances \
            --filters "Name=tag:Project,Values=${PROJECT_TAG}" \
                      "Name=instance-state-name,Values=pending,running,stopping,stopped" \
            --query 'Reservations[].Instances[].InstanceId' --output text
        if [[ -n "${INSTANCE_NAME:-}" ]]; then
            awsr "${REGION}" ec2 describe-instances \
                --filters "Name=tag:Name,Values=${INSTANCE_NAME}" \
                          "Name=instance-state-name,Values=pending,running,stopping,stopped" \
                --query 'Reservations[].Instances[].InstanceId' --output text
        fi
    } | tr '\t' '\n' | sed '/^$/d' | sort -u
)

read_lines_into ALLOC_IDS < <(
    {
        awsr "${REGION}" ec2 describe-addresses \
            --filters "Name=tag:Project,Values=${PROJECT_TAG}" \
            --query 'Addresses[].AllocationId' --output text
        for iid in ${INSTANCE_IDS[@]+"${INSTANCE_IDS[@]}"}; do
            awsr "${REGION}" ec2 describe-addresses \
                --filters "Name=instance-id,Values=${iid}" \
                --query 'Addresses[].AllocationId' --output text
        done
    } | tr '\t' '\n' | sed '/^$/d' | sort -u
)

read_lines_into SG_IDS < <(
    {
        awsr "${REGION}" ec2 describe-security-groups \
            --filters "Name=tag:Project,Values=${PROJECT_TAG}" \
            --query 'SecurityGroups[].GroupId' --output text
        if [[ -n "${SECURITY_GROUP_NAME:-}" ]]; then
            awsr "${REGION}" ec2 describe-security-groups \
                --filters "Name=group-name,Values=${SECURITY_GROUP_NAME}" \
                --query 'SecurityGroups[].GroupId' --output text
        fi
    } | tr '\t' '\n' | sed '/^$/d' | sort -u
)

echo ""
echo "Planned teardown in ${REGION}:"
echo "  Instances:       ${INSTANCE_IDS[*]:-<none>}"
echo "  Elastic IPs:     ${ALLOC_IDS[*]:-<none>}"
echo "  Security groups: ${SG_IDS[*]:-<none>}"
if [[ ${DELETE_DNS} -eq 1 ]]; then
    echo "  DNS:             delete A records for ${DOMAIN:-<DOMAIN unset>} ${EXTRA_A_RECORDS:-} (zone ${ROUTE53_ZONE_ID:-<unset>})"
else
    echo "  DNS:             left intact (pass --delete-dns to remove A records)"
fi
echo ""
echo "  NOTE: key pairs are NOT deleted (harmless, free, needed to reuse the .pem)."
echo ""

if [[ ${#INSTANCE_IDS[@]} -eq 0 && ${#ALLOC_IDS[@]} -eq 0 && ${#SG_IDS[@]} -eq 0 && ${DELETE_DNS} -eq 0 ]]; then
    log "Nothing matching Project=${PROJECT_TAG} or configured names found. Already clean."
    exit 0
fi

confirm "Delete the above resources? This is destructive." || die "Aborted by user."

# ---------------------------------------------------------------------------
# 1. Elastic IPs (disassociate then release)
# ---------------------------------------------------------------------------
for alloc in ${ALLOC_IDS[@]+"${ALLOC_IDS[@]}"}; do
    assoc="$(awsr "${REGION}" ec2 describe-addresses --allocation-ids "${alloc}" \
        --query 'Addresses[0].AssociationId' --output text 2>/dev/null || echo "None")"
    if [[ "${assoc}" != "None" && -n "${assoc}" ]]; then
        log "Disassociating EIP ${alloc} (assoc ${assoc})..."
        awsr "${REGION}" ec2 disassociate-address --association-id "${assoc}" || true
    fi
    log "Releasing EIP ${alloc}..."
    awsr "${REGION}" ec2 release-address --allocation-id "${alloc}" || warn "Could not release ${alloc}."
done

# ---------------------------------------------------------------------------
# 2. Instances (terminate; root volume is DeleteOnTermination=true)
# ---------------------------------------------------------------------------
if [[ ${#INSTANCE_IDS[@]} -gt 0 ]]; then
    log "Terminating instances: ${INSTANCE_IDS[*]}..."
    awsr "${REGION}" ec2 terminate-instances --instance-ids "${INSTANCE_IDS[@]}" >/dev/null
    log "Waiting for termination (releases the SG dependency)..."
    awsr "${REGION}" ec2 wait instance-terminated --instance-ids "${INSTANCE_IDS[@]}"
fi

# ---------------------------------------------------------------------------
# 3. Security groups (only after instances are gone)
# ---------------------------------------------------------------------------
for sg in ${SG_IDS[@]+"${SG_IDS[@]}"}; do
    sg_name="$(awsr "${REGION}" ec2 describe-security-groups --group-ids "${sg}" \
        --query 'SecurityGroups[0].GroupName' --output text 2>/dev/null || echo "")"
    if [[ "${sg_name}" == "default" ]]; then
        warn "Refusing to delete the VPC default security group ${sg}."
        continue
    fi
    log "Deleting security group ${sg} (${sg_name})..."
    awsr "${REGION}" ec2 delete-security-group --group-id "${sg}" \
        || warn "Could not delete ${sg} (still in use? default SG?). Skipping."
done

# ---------------------------------------------------------------------------
# 4. Route 53 A record (opt-in)
# ---------------------------------------------------------------------------
if [[ ${DELETE_DNS} -eq 1 ]]; then
    if [[ -n "${ROUTE53_ZONE_ID:-}" && -n "${DOMAIN:-}" ]]; then
        for rec in ${DOMAIN} ${EXTRA_A_RECORDS:-}; do
            current="$(aws route53 list-resource-record-sets --hosted-zone-id "${ROUTE53_ZONE_ID}" \
                --query "ResourceRecordSets[?Name=='${rec}.' && Type=='A']" --output json)"
            if [[ "$(echo "${current}" | jq 'length')" -gt 0 ]]; then
                log "Deleting A record ${rec}..."
                batch="$(echo "${current}" | jq -c '{Changes:[{Action:"DELETE",ResourceRecordSet:.[0]}]}')"
                aws route53 change-resource-record-sets --hosted-zone-id "${ROUTE53_ZONE_ID}" \
                    --change-batch "${batch}" >/dev/null
            else
                warn "No A record for ${rec} in zone ${ROUTE53_ZONE_ID}; nothing to delete."
            fi
        done
    else
        warn "--delete-dns given but ROUTE53_ZONE_ID/DOMAIN not set; skipping."
    fi
fi

cat <<EOF

[destroy] Teardown complete for Project=${PROJECT_TAG} in ${REGION}.

Still costing money / still present (by design):
  - Default VPC (free).
  - Route 53 hosted zone (~\$0.50/mo) unless you deleted it manually.
  - EC2 key pair (free) — kept so you can reuse the .pem.
  - Any manual EBS snapshots / S3 backups you made (that's the point).

To confirm nothing compute/network remains, re-run: deploy/aws/scan.sh ${REGION}
EOF
