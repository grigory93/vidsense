#!/usr/bin/env bash
# VidSense — read-only AWS account inventory.
#
# Scans the account for every resource that could be part of the vidsense
# deployment (or cost money), across all enabled regions plus global services,
# and writes a raw JSON snapshot + a human-readable Markdown summary under
# deploy/aws/inventory/ (gitignored).
#
# This script NEVER modifies anything. Run it before freezing so create.sh can
# be filled in from real values, and again after recreate to confirm parity.
#
# Usage:
#   aws sso login                 # refresh credentials first
#   deploy/aws/scan.sh            # scan all regions
#   deploy/aws/scan.sh us-east-1  # scan only the given region(s)
#
# Requires: aws CLI, jq.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

command -v jq >/dev/null 2>&1 || die "jq not found. Install jq (brew install jq / apt install jq)."

load_config
require_aws

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${INVENTORY_DIR}"
RAW_JSON="${INVENTORY_DIR}/${TIMESTAMP}.json"
SUMMARY_MD="${INVENTORY_DIR}/${TIMESTAMP}.summary.md"

ACCOUNT="$(account_id)"
log "Scanning AWS account ${ACCOUNT} at ${TIMESTAMP} (read-only)."

# Region list: CLI args override auto-detect.
if [[ $# -gt 0 ]]; then
    REGIONS=("$@")
else
    read_lines_into REGIONS < <(all_regions)
fi
[[ ${#REGIONS[@]} -gt 0 ]] || die "No regions to scan."
log "Regions: ${REGIONS[*]}"

# jq helper: run an aws command, capture JSON, default to null on failure so a
# restricted API in one region does not abort the whole scan.
capture() {
    local out
    if out="$("$@" 2>/dev/null)"; then
        [[ -n "${out}" ]] && echo "${out}" || echo 'null'
    else
        echo 'null'
    fi
}

# Start the JSON document.
echo "{" > "${RAW_JSON}"
printf '  "account": "%s",\n' "${ACCOUNT}" >> "${RAW_JSON}"
printf '  "scanned_at": "%s",\n' "${TIMESTAMP}" >> "${RAW_JSON}"
printf '  "regions": %s,\n' "$(printf '%s\n' "${REGIONS[@]}" | jq -R . | jq -s -c .)" >> "${RAW_JSON}"

# ---------------------------------------------------------------------------
# Per-region EC2-family resources
# ---------------------------------------------------------------------------
echo '  "by_region": {' >> "${RAW_JSON}"
first_region=1
for region in "${REGIONS[@]}"; do
    log "  region ${region}..."
    [[ ${first_region} -eq 1 ]] && first_region=0 || echo ',' >> "${RAW_JSON}"

    instances="$(capture awsr "${region}" ec2 describe-instances --output json)"
    sgs="$(capture awsr "${region}" ec2 describe-security-groups --output json)"
    eips="$(capture awsr "${region}" ec2 describe-addresses --output json)"
    keys="$(capture awsr "${region}" ec2 describe-key-pairs --output json)"
    volumes="$(capture awsr "${region}" ec2 describe-volumes --output json)"
    snapshots="$(capture awsr "${region}" ec2 describe-snapshots --owner-ids self --output json)"
    log_groups="$(capture awsr "${region}" logs describe-log-groups --output json)"

    printf '    "%s": {\n' "${region}" >> "${RAW_JSON}"
    printf '      "instances": %s,\n' "${instances}" >> "${RAW_JSON}"
    printf '      "security_groups": %s,\n' "${sgs}" >> "${RAW_JSON}"
    printf '      "elastic_ips": %s,\n' "${eips}" >> "${RAW_JSON}"
    printf '      "key_pairs": %s,\n' "${keys}" >> "${RAW_JSON}"
    printf '      "volumes": %s,\n' "${volumes}" >> "${RAW_JSON}"
    printf '      "snapshots": %s,\n' "${snapshots}" >> "${RAW_JSON}"
    printf '      "log_groups": %s\n' "${log_groups}" >> "${RAW_JSON}"
    printf '    }' >> "${RAW_JSON}"
done
echo '' >> "${RAW_JSON}"
echo '  },' >> "${RAW_JSON}"

# ---------------------------------------------------------------------------
# Global / account-wide services
# ---------------------------------------------------------------------------
log "  global services (Route 53, S3, IAM, Backup)..."
route53_zones="$(capture aws route53 list-hosted-zones --output json)"
s3_buckets="$(capture aws s3api list-buckets --output json)"
iam_users="$(capture aws iam list-users --output json)"
iam_roles="$(capture aws iam list-roles --output json)"
backup_plans="$(capture aws backup list-backup-plans --output json)"

# Route 53 record sets for each hosted zone (helps match SSH_HOST / domain).
route53_records='{}'
if [[ "${route53_zones}" != "null" ]]; then
    zone_ids="$(echo "${route53_zones}" | jq -r '.HostedZones[].Id' 2>/dev/null || true)"
    for zid in ${zone_ids}; do
        recs="$(capture aws route53 list-resource-record-sets --hosted-zone-id "${zid}" --output json)"
        route53_records="$(jq -c --arg z "${zid}" --argjson r "${recs}" '. + {($z): $r}' <<<"${route53_records}")"
    done
fi

printf '  "global": {\n' >> "${RAW_JSON}"
printf '    "route53_zones": %s,\n' "${route53_zones}" >> "${RAW_JSON}"
printf '    "route53_records": %s,\n' "${route53_records}" >> "${RAW_JSON}"
printf '    "s3_buckets": %s,\n' "${s3_buckets}" >> "${RAW_JSON}"
printf '    "iam_users": %s,\n' "${iam_users}" >> "${RAW_JSON}"
printf '    "iam_roles": %s,\n' "${iam_roles}" >> "${RAW_JSON}"
printf '    "backup_plans": %s\n' "${backup_plans}" >> "${RAW_JSON}"
printf '  }\n' >> "${RAW_JSON}"
echo "}" >> "${RAW_JSON}"

# Validate JSON; if malformed, keep the file for debugging but fail loudly.
jq empty "${RAW_JSON}" 2>/dev/null || die "Generated ${RAW_JSON} is not valid JSON (kept for inspection)."

# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------
log "Writing summary ${SUMMARY_MD}..."
{
    echo "# VidSense AWS inventory"
    echo ""
    echo "- Account: \`${ACCOUNT}\`"
    echo "- Scanned: ${TIMESTAMP}"
    echo "- Regions scanned: ${REGIONS[*]}"
    echo "- Raw data: \`$(basename "${RAW_JSON}")\`"
    echo ""
    echo "> Anything tagged or named with **vidsense** is highlighted below. Review"
    echo "> the raw JSON for full detail before running create.sh / destroy.sh."
    echo ""

    echo "## EC2 instances (all regions)"
    echo ""
    echo "| Region | InstanceId | Name | Type | State | PublicIp | PrivateIp |"
    echo "|--------|-----------|------|------|-------|----------|-----------|"
    jq -r '
      .by_region | to_entries[] as $r
      | ($r.value.instances.Reservations // [])[]?.Instances[]?
      | [ $r.key, .InstanceId,
          ((.Tags // []) | map(select(.Key=="Name")) | .[0].Value // "-"),
          .InstanceType, .State.Name, (.PublicIpAddress // "-"), (.PrivateIpAddress // "-") ]
      | "| " + join(" | ") + " |"
    ' "${RAW_JSON}"
    echo ""

    echo "## Elastic IPs"
    echo ""
    echo "| Region | PublicIp | AllocationId | AssociatedInstance |"
    echo "|--------|----------|--------------|--------------------|"
    jq -r '
      .by_region | to_entries[] as $r
      | ($r.value.elastic_ips.Addresses // [])[]?
      | [ $r.key, (.PublicIp // "-"), (.AllocationId // "-"), (.InstanceId // "-") ]
      | "| " + join(" | ") + " |"
    ' "${RAW_JSON}"
    echo ""

    echo "## Security groups (non-default)"
    echo ""
    echo "| Region | GroupId | Name | IngressPorts |"
    echo "|--------|---------|------|--------------|"
    jq -r '
      .by_region | to_entries[] as $r
      | ($r.value.security_groups.SecurityGroups // [])[]?
      | select(.GroupName != "default")
      | [ $r.key, .GroupId, .GroupName,
          ([ (.IpPermissions // [])[]? | (.FromPort|tostring) ] | join(",")) ]
      | "| " + join(" | ") + " |"
    ' "${RAW_JSON}"
    echo ""

    echo "## EBS volumes"
    echo ""
    echo "| Region | VolumeId | SizeGiB | Type | State | Attached |"
    echo "|--------|----------|---------|------|-------|----------|"
    jq -r '
      .by_region | to_entries[] as $r
      | ($r.value.volumes.Volumes // [])[]?
      | [ $r.key, .VolumeId, (.Size|tostring), .VolumeType, .State,
          ((.Attachments // []) | map(.InstanceId) | join(",") | if .=="" then "-" else . end) ]
      | "| " + join(" | ") + " |"
    ' "${RAW_JSON}"
    echo ""

    echo "## Route 53 hosted zones"
    echo ""
    echo "| ZoneId | Name | RecordCount |"
    echo "|--------|------|-------------|"
    jq -r '
      (.global.route53_zones.HostedZones // [])[]?
      | [ .Id, .Name, (.ResourceRecordSetCount|tostring) ]
      | "| " + join(" | ") + " |"
    ' "${RAW_JSON}"
    echo ""

    echo "## S3 buckets"
    echo ""
    jq -r '(.global.s3_buckets.Buckets // [])[]? | "- " + .Name' "${RAW_JSON}"
    echo ""

    echo "## Resources matching \"vidsense\""
    echo ""
    echo "These are the likely-relevant resources to recreate/destroy:"
    echo ""
    jq -r '
      [
        (.by_region | to_entries[] as $r
          | ($r.value.instances.Reservations // [])[]?.Instances[]?
          | select( ((.Tags // []) | map(.Value) | join(" ") | ascii_downcase | test("vidsense")) )
          | "instance " + .InstanceId + " " + ((.Tags // []) | map(select(.Key=="Name")) | .[0].Value // "") + " (" + $r.key + ")"),
        (.by_region | to_entries[] as $r
          | ($r.value.security_groups.SecurityGroups // [])[]?
          | select(.GroupName | ascii_downcase | test("vidsense"))
          | "security-group " + .GroupId + " " + .GroupName + " (" + $r.key + ")"),
        (.by_region | to_entries[] as $r
          | ($r.value.key_pairs.KeyPairs // [])[]?
          | select(.KeyName | ascii_downcase | test("vidsense"))
          | "key-pair " + .KeyName + " (" + $r.key + ")"),
        (.by_region | to_entries[] as $r
          | ($r.value.elastic_ips.Addresses // [])[]?
          | select((.InstanceId // "") != "")
          | "elastic-ip " + .PublicIp + " -> " + .InstanceId + " (" + $r.key + ")"),
        ((.global.route53_zones.HostedZones // [])[]?
          | select(.Name | ascii_downcase | test("vidsense"))
          | "route53-zone " + .Id + " " + .Name),
        ((.global.s3_buckets.Buckets // [])[]?
          | select(.Name | ascii_downcase | test("vidsense"))
          | "s3-bucket " + .Name)
      ]
      | if length == 0 then "- (none found — confirm you scanned the right account/region)"
        else (.[] | "- " + .) end
    ' "${RAW_JSON}"
} > "${SUMMARY_MD}"

log "Done."
log "Raw:     ${RAW_JSON}"
log "Summary: ${SUMMARY_MD}"
echo ""
echo "Next: review the summary, then copy real values (region, instance type, SG"
echo "rules, hosted zone id) into deploy/aws/config.env for create.sh."
