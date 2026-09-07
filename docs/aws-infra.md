# AWS infrastructure: freeze and recreate

This is the "from zero / tear it all down / rebuild later" runbook for the
AWS resources behind `vidsense.info`. **Commands and the agent playbook live
in [deploy/aws/README.md](../deploy/aws/README.md)** — start there to freeze
or recreate. This page keeps the scanned inventory, cost notes, and
architecture. It complements [deployment-aws.md](deployment-aws.md)
(the console walkthrough) and [deployment.md](deployment.md) (provider-agnostic
VM checklist).

## What is (and is not) in AWS

GitHub Actions does **not** provision AWS. [ci.yml](../.github/workflows/ci.yml)
runs lint + tests on GitHub-hosted runners; [deploy.yml](../.github/workflows/deploy.yml)
only **SSHes into an already-existing EC2 VM** and runs [deploy/update.sh](../deploy/update.sh).
So "the AWS infra" is a small, well-understood set of resources:

```mermaid
flowchart LR
  push[push to main]
  ci[ci.yml lint+test]
  deploy[deploy.yml]
  host["Elastic IP / SSH_HOST"]
  vm[EC2 Ubuntu VM]
  caddy[Caddy 80/443]
  app[Uvicorn 127.0.0.1:8000]
  disk["SQLite + FAISS on EBS"]

  push --> ci --> deploy
  deploy -->|SSH| host --> vm
  vm --> caddy --> app --> disk
```

| In AWS (this runbook manages) | Not in AWS (manage elsewhere) |
|-------------------------------|-------------------------------|
| 1 EC2 instance (Ubuntu 24.04) | GitHub repo + Actions secrets |
| Security group (22 / 80 / 443) | Domain registrar (if not Route 53) |
| Elastic IP | Webshare residential proxy account |
| EBS root volume (SQLite + FAISS) | YouTube / LLM API keys |
| EC2 key pair | VM-local `.env` + Caddy basicauth hash |
| (optional) Route 53 hosted zone + A record | |

There is **no** ECS, ECR, ALB, CloudFront, RDS, Lambda, or app-level AWS SDK
usage. The app persists everything to the VM disk, so **terminating the
instance destroys your data** unless you back it up first.

## Live inventory (scanned 2026-09-07)

Account `682664623193`, all enabled regions. The only running compute is in
**us-east-1**. These values are now the defaults in
[config.example.env](../deploy/aws/config.example.env). Raw JSON lives in
`deploy/aws/inventory/` (gitignored).

| Resource | Live value |
|----------|------------|
| Instance | `i-0747de6d053cf0f18` — Name `vidsense-dev-t3med`, **t2.medium** (not t3), running |
| AMI | `ami-0ec10929233384c7f` — Ubuntu 24.04 LTS (`ubuntu-noble-24.04-amd64-server-20260313`) |
| Key pair | `vidsensed-dev` (note the extra "d") |
| Public IP / EIP | `35.153.113.30` (`eipalloc-0b5b077663b655365`) |
| VPC / subnet / AZ | default VPC `vpc-4ed69936`, `subnet-bcc97fe1`, `us-east-1a` |
| Security group | `sg-0de9be902da838b02` (`launch-wizard-3`): inbound 22/80/443 from `0.0.0.0/0` |
| Root volume | `vol-0c4c219e610d5d6fb` — 20 GiB gp3, DeleteOnTermination=true |
| Route 53 | hosted zone `Z09014773OXLG8IMZNHX8` for `vidsense.info.` |
| DNS A records | `vidsense.info` and `vidsense.vidsense.info` → `35.153.113.30` (TTL 300) |
| Tags | only `Name=vidsense-dev-t3med` — **no `Project=vidsense` tag** |
| Snapshots / AWS Backup | none |

**Not part of vidsense** (leave alone unless you know you want them gone): unused
security groups in us-east-1/us-east-2 named `launch-wizard-*`, `H2O-ai
Driverless AI*`, `particle-demo-mysql-sg`; key pairs `EC2 Tutorial` and
`vidsense` in us-east-2; S3 buckets `aws-cloudtrail-logs-682664623193-c87d53c7`
and `psilabs-public-files`. No IAM users.

`destroy.sh` matches the live instance by **Name tag** and the SG by **group
name** as well as `Project=vidsense`, so the current untagged VM can still be
torn down. `create.sh` will tag everything it makes going forward.

## The scripts

All live in [deploy/aws/](../deploy/aws/) and are plain AWS CLI + bash (no
Terraform, no state file to rot during a long freeze). Every resource
`create.sh` makes is tagged `Project=vidsense`, which is exactly what
`destroy.sh` selects.

| Script | Does | Modifies AWS? |
|--------|------|---------------|
| `scan.sh` | Inventories the whole account (all regions) → `deploy/aws/inventory/` | No (read-only) |
| `backup-vm.sh` | Pulls `data/`, `.env`, Caddyfile off the VM → `deploy/aws/backups/` | No |
| `restore-vm.sh` | Pushes a `backup-vm.sh` archive onto a new VM (optional `--start`) | No (SSH only) |
| `create.sh` | Recreates SG + key pair + EC2 + EIP + (opt) DNS in the default VPC, then runs `bootstrap.sh` | Yes |
| `destroy.sh` | Terminates instance, releases EIP, deletes SG (leaves the default VPC) | Yes (destructive) |
| `config.example.env` | Template of non-secret parameters → copy to `config.env` | n/a |

Prerequisites: `aws` CLI (authenticated — `aws sso login`), `jq`, `ssh`/`scp`.
`config.env`, `inventory/`, and `backups/` are gitignored — they hold account
IDs, IPs, and secrets.

## Freeze (tear down to save money)

Canonical commands: [deploy/aws/README.md](../deploy/aws/README.md#freeze-stop-paying-for-the-vm).
Do this in order. Steps 1–2 are read-only / safe; step 4 is destructive.

1. **Authenticate and inventory.**
   ```bash
   aws sso login
   deploy/aws/scan.sh
   ```
   Read `deploy/aws/inventory/<timestamp>.summary.md`. Confirm which instance,
   Elastic IP, security group, and (maybe) Route 53 zone are the real vidsense
   ones, and note the **region**. Copy those non-secret facts into
   `deploy/aws/config.env`:
   ```bash
   cp deploy/aws/config.example.env deploy/aws/config.env
   $EDITOR deploy/aws/config.env   # AWS_REGION, INSTANCE_TYPE, ROUTE53_ZONE_ID, etc.
   ```

2. **Back up the VM** (irreplaceable — SQLite DB, FAISS indexes, `.env`, Caddy
   config). Use the current `SSH_HOST` (the Elastic IP or `vidsense.info`):
   ```bash
   deploy/aws/backup-vm.sh                  # defaults: vidsense.info as ubuntu with vidsensed-dev.pem
   # or: deploy/aws/backup-vm.sh vidsense-dev ubuntu
   ```
   Then **copy the resulting `deploy/aws/backups/*.tar.gz` somewhere durable
   outside this repo** (it contains secrets). Verify it opens:
   ```bash
   tar tzf deploy/aws/backups/vidsense-vm-*.tar.gz
   ```

3. **Stop auto-deploy** so teardown does not turn every future `main` push red.
   The push trigger in [deploy.yml](../.github/workflows/deploy.yml) is already
   commented out for the freeze; `workflow_dispatch` still works if you want to
   redeploy manually later. Nothing to do unless you re-enabled it.
   Optionally clear the stale host so a manual run can't hit a recycled IP:
   ```bash
   gh secret set SSH_HOST --env dev --body "frozen" --repo grigory93/vidsense
   ```

4. **Destroy the AWS resources.**
   ```bash
   deploy/aws/destroy.sh              # keeps the Route 53 zone (~$0.50/mo, keeps DNS)
   # deploy/aws/destroy.sh --delete-dns   # also removes the DOMAIN A record
   ```
   It prints the exact resources and waits for you to type `yes`. Key pairs are
   intentionally kept (free) so you can reuse the `.pem`.

5. **Confirm it's gone** (and you've stopped paying for compute):
   ```bash
   deploy/aws/scan.sh "$AWS_REGION"
   ```

### What still costs money after a freeze

- Route 53 hosted zone: roughly **$0.50/month per zone** (I believe this is the
  current AWS price — verify on the [Route 53 pricing page](https://aws.amazon.com/route53/pricing/)).
  Delete the zone in the console if you want truly $0, but you then lose the DNS
  config and, depending on your registrar, may need to reconfigure name servers.
- Any manual EBS snapshots or S3 backups you created (that's the point of them).
- Domain registration renewal (billed by your registrar, not affected by teardown).

## Recreate (rebuild later)

Canonical commands: [deploy/aws/README.md](../deploy/aws/README.md#recreate-bring-the-site-back).

1. **Provision.**
   ```bash
   aws sso login
   deploy/aws/create.sh
   ```
   This creates the SG, **reuses** `~/.ssh/vidsensed-dev.pem` (never overwrites
   it; imports the public key into AWS if the pair was deleted), launches
   Ubuntu 24.04 EC2 with a gp3 root volume, an Elastic IP, optionally the
   Route 53 A records, then runs [deploy/bootstrap.sh](../deploy/bootstrap.sh).
   It prints the new public IP.

   Your `~/.ssh/config` `Host vidsense-dev` `IdentityFile` stays the same. After
   recreate, update **only** `HostName` to the new Elastic IP (the old
   `35.153.113.30` is released on destroy). Then `ssh vidsense-dev` works as
   before.

2. **Restore state / secrets** on the VM. Prefer the helper (it unpacks the
   outer archive correctly — do not `tar` the outer file straight onto `/`):
   ```bash
   deploy/aws/restore-vm.sh --start deploy/aws/backups/vidsense-vm-<ts>.tar.gz <new-ip>
   ```
   That writes `/opt/vidsense/data`, `/opt/vidsense/.env`, and
   `/etc/caddy/Caddyfile`, then reloads Caddy and starts `vidsense`. Or create
   a fresh `/opt/vidsense/.env` per [deployment-aws.md §8](deployment-aws.md#8-configure-secrets-and-environment)
   (`APP_SECRET_KEY`, `YOUTUBE_API_KEY`, LLM keys, `APP_ALLOWED_HOSTS`,
   `WEBSHARE_PROXY_*`) and configure Caddy by hand.

3. **DNS.** If `create.sh` did not update Route 53 (no `ROUTE53_ZONE_ID`, or the
   domain is at an external registrar), point the A record for `vidsense.info`
   at the new Elastic IP.

4. **Re-wire GitHub deploy** so CD works again:
   ```bash
   gh secret set SSH_HOST --env dev --body "<new-ip-or-vidsense.info>" --repo grigory93/vidsense
   gh secret set SSH_USER --env dev --body "vidsense" --repo grigory93/vidsense
   # SSH_PRIVATE_KEY: reuse the existing deploy key, or generate a new pair and add
   # its PUBLIC key to /opt/vidsense/.ssh/authorized_keys on the VM.
   # Optional: pin host keys from the NEW VM (not the backup — those are stale):
   # ssh-keyscan -H <new-ip> | gh secret set SSH_KNOWN_HOSTS --env dev --repo grigory93/vidsense
   ```
   Then re-enable the push trigger in [deploy.yml](../.github/workflows/deploy.yml)
   (uncomment the `push:` block) and merge.

5. **Smoke test** per [deployment-aws.md §11](deployment-aws.md#11-smoke-test):
   ```bash
   curl -I http://vidsense.info
   curl -u admin:<password> https://vidsense.info
   ```

## Notes and limits

- `create.sh` uses the account **default VPC** (`vpc-4ed69936` in us-east-1).
  A default VPC is free. The Cost Explorer “VPC” line (~$3.72/mo) is the
  public IPv4 / Elastic IP (`USE1-PublicIPv4:InUseAddress`), not the VPC.
- Live SSH ingress is `0.0.0.0/0` on port 22. That is a real security
  trade-off: GitHub-hosted deploy runners have a wide, changing IP range, so
  locking port 22 to your admin IP would break CD-over-SSH. Set
  `SSH_INGRESS_CIDR` in `config.env` deliberately.
- `destroy.sh` never deletes a hosted zone, key pair, or the default VPC. It
  selects instances / EIPs / SGs tagged `Project=vidsense` **or** matching
  `INSTANCE_NAME` / `SECURITY_GROUP_NAME` in `config.env`.
- These scripts can later be imported into Terraform if you outgrow bash; the
  consistent `Project=vidsense` tagging makes that straightforward.
