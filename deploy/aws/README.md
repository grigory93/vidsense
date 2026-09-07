# VidSense AWS — freeze and recreate

This directory is the **operator and agent playbook** for the AWS stack behind
[`vidsense.info`](https://vidsense.info). Use it to:

1. **Inventory** what is running.
2. **Back up** irreplaceable VM state.
3. **Destroy** the paid compute so the project can sit frozen.
4. **Recreate** the same stack later and restore the site.

Narrative context (live inventory, cost notes, why the default VPC):
[`docs/aws-infra.md`](../../docs/aws-infra.md). Day-to-day VM setup:
[`docs/deployment-aws.md`](../../docs/deployment-aws.md).

GitHub Actions does **not** provision AWS. [`deploy.yml`](../../.github/workflows/deploy.yml)
only SSHes into an already-existing EC2 box and runs [`deploy/update.sh`](../update.sh).
These scripts are what create and delete that box.

---

## What is in AWS (and what is not)

```
Internet → Route 53 (vidsense.info) → Elastic IP → EC2 Ubuntu 24.04
                                              → Caddy :80/:443
                                              → Uvicorn 127.0.0.1:8000
                                              → SQLite + FAISS on the EBS root volume
```

| Managed here | Not in AWS — keep elsewhere |
|--------------|-----------------------------|
| 1 EC2 instance (Ubuntu 24.04, currently `t2.medium`) | GitHub repo + Actions secrets (`SSH_*`) |
| Security group (22 / 80 / 443) | Domain registrar / Route 53 hosted zone (kept) |
| Elastic IP | Webshare residential proxy account |
| EBS root volume (SQLite + FAISS + `.env`) | YouTube / LLM API keys |
| EC2 key pair **name** in AWS (the `.pem` stays on your laptop) | VM-local `.env` and Caddy basicauth hash |

There is no ECS, ECR, ALB, CloudFront, RDS, or Lambda. **Terminating the
instance deletes the database and secrets** unless you ran `backup-vm.sh` first.

Scripts use the account **default VPC** (free). Do not create a dedicated VPC.
The Cost Explorer “VPC” line is the public IPv4 / Elastic IP charge.

---

## Files

| Path | Role | Changes AWS? |
|------|------|--------------|
| `scan.sh` | All-region inventory → `inventory/` | No |
| `backup-vm.sh` | Pull `data/`, `.env`, Caddyfile off the live VM → `backups/` | No |
| `create.sh` | SG + key pair + EC2 + EIP + optional DNS, then `bootstrap.sh` | Yes |
| `restore-vm.sh` | Push a `backup-vm.sh` archive onto a new VM | No (SSH only) |
| `destroy.sh` | Terminate instance, release EIP, delete SG | Yes — destructive |
| `_lib.sh` | Shared helpers. Not executable. | — |
| `config.example.env` | Non-secret parameter template (tracked) | — |
| `config.env` | Your filled-in copy (**gitignored**) | — |
| `inventory/` | Scan output (**gitignored**) | — |
| `backups/` | VM tarballs with secrets (**gitignored**) | — |

`config.example.env` already has the values from the 2026-09-07 live scan
(instance name, SG name, key pair, Route 53 zone). Copy it to `config.env`
and only edit if the scan shows something different.

---

## Prerequisites

On the laptop that will run the scripts:

- `aws` CLI v2, authenticated (`aws sso login` or equivalent)
- `jq`, `ssh`, `scp`, `ssh-keygen`, `tar`
- Local private key at `KEY_PAIR_FILE` (default `~/.ssh/vidsensed-dev.pem`)
- `deploy/aws/config.env` present (see below)

```bash
cp deploy/aws/config.example.env deploy/aws/config.env   # once
aws sso login
aws sts get-caller-identity     # must print account 682664623193 (or the current one)
```

If `get-caller-identity` says the token expired, run `aws sso login` in a
real terminal (browser SSO cannot be completed from a non-interactive agent).

---

## Safety rules (read before any command)

These apply to humans and to a later agent equally.

1. **Never run `destroy.sh` without a verified backup.** `deploy/aws/backups/`
   must contain a `vidsense-vm-*.tar.gz` whose inner payload includes
   `opt/vidsense/.env`, `opt/vidsense/data/`, and `etc/caddy/Caddyfile`.
   Then **copy that tarball somewhere durable outside this repo** (it has
   production secrets).
2. **Never print `.env` values, Caddy password hashes, or private keys.**
   Scripts already mask values; do not `cat` those files into the chat.
3. **Never commit** `config.env`, `inventory/`, or `backups/`. They are gitignored.
4. **`destroy.sh` requires typing `yes`.** Do not pipe `yes` into it unless
   the human has explicitly authorized destroy in this conversation.
5. **Do not delete** the Route 53 hosted zone, the default VPC, or
   `~/.ssh/vidsensed-dev.pem`. `destroy.sh` already leaves those alone.
6. **Do not run `create.sh` and `destroy.sh` in the same breath.** Freeze
   is backup → destroy. Recreate is create → restore. Confirm each step.
7. **Region is `us-east-1`.** Other regions have leftover `launch-wizard-*`
   security groups that are **not** VidSense. `destroy.sh` only touches
   `AWS_REGION`.
8. **Two different SSH keys exist.** Do not mix them (see [Keys](#keys-and-secrets)).
9. **Webshare is not an AWS resource.** Credentials live only in the VM
   `.env`. They survive freeze only if the backup captured them and the
   Webshare subscription is still active.

---

## Freeze (stop paying for the VM)

Do these in order. Steps 1–2 are safe. Step 4 is destructive.

### 1. Authenticate and scan

```bash
aws sso login
deploy/aws/scan.sh
```

Read `deploy/aws/inventory/<timestamp>.summary.md`. Confirm the VidSense
instance is in **us-east-1**, note its public IP, and that `config.env`
matches (`INSTANCE_NAME`, `SECURITY_GROUP_NAME`, `KEY_PAIR_NAME`,
`ROUTE53_ZONE_ID`).

Expected live shape (scanned 2026-09-07; IDs will change after recreate):

- Instance `vidsense-dev-t3med`, type **`t2.medium`** (the name says t3)
- Key pair `vidsensed-dev` ↔ `~/.ssh/vidsensed-dev.pem`
- SG `launch-wizard-3` (22/80/443)
- Route 53 zone `Z09014773OXLG8IMZNHX8` for `vidsense.info`
- Extra A record: `vidsense.vidsense.info`

### 2. Back up the VM

```bash
deploy/aws/backup-vm.sh                  # vidsense.info as ubuntu + vidsensed-dev.pem
# or: deploy/aws/backup-vm.sh vidsense-dev
# or: deploy/aws/backup-vm.sh 35.153.113.30 ubuntu ~/.ssh/vidsensed-dev.pem
```

The script fails loudly if `/opt/vidsense/data`, `/opt/vidsense/.env`, or
`/etc/caddy/Caddyfile` is missing. It lists `.env` **keys** (not values) and
warns if `WEBSHARE_PROXY_USERNAME` / `WEBSHARE_PROXY_PASSWORD` are absent.

```bash
# Verify the archive, then copy it OFF this machine / out of the repo
tar tzf deploy/aws/backups/vidsense-vm-*.tar.gz
# must list: payload.tar.gz  and  known_hosts
STAGE=$(mktemp -d)
tar xzf deploy/aws/backups/vidsense-vm-*.tar.gz -C "$STAGE"
tar tzf "$STAGE/payload.tar.gz" | grep -E 'opt/vidsense/\.env|opt/vidsense/data/|etc/caddy/Caddyfile'
rm -rf "$STAGE"
```

**Stop here if the backup is missing, incomplete, or Webshare keys are
absent and you still need YouTube transcripts after recreate.**

### 3. Keep auto-deploy off

The `push: branches: [main]` trigger in `.github/workflows/deploy.yml` is
already commented out. Leave it that way until recreate is done. Optional:

```bash
gh secret set SSH_HOST --env dev --body "frozen" --repo grigory93/vidsense
```

### 4. Destroy

```bash
deploy/aws/destroy.sh                 # keeps Route 53 zone + A records
# deploy/aws/destroy.sh --delete-dns  # also deletes the A records (zone stays)
```

It prints instance IDs, EIP allocations, and SG IDs, then waits for `yes`.
Key pairs are kept (free) so the same `.pem` still works later.

### 5. Confirm compute is gone

```bash
deploy/aws/scan.sh us-east-1
```

The summary should show **no** running `vidsense-dev-t3med` instance and
**no** Elastic IP. The hosted zone may still be there (~$0.50/month).

---

## Recreate (bring the site back)

### 1. Provision

```bash
aws sso login
deploy/aws/create.sh
```

Idempotent. Reuses an instance / EIP / SG if one already matches
`Project=vidsense` or `INSTANCE_NAME`. Creates:

1. Security group in the **default VPC** (22 from `SSH_INGRESS_CIDR`, 80/443
   from anywhere)
2. Key pair — **reuses** `~/.ssh/vidsensed-dev.pem`; never overwrites it;
   imports the public half into AWS if the pair was deleted
3. Ubuntu 24.04 `t2.medium` with a 20 GiB gp3 root volume
4. Elastic IP, associated to the instance
5. Route 53 A records for `vidsense.info` and `EXTRA_A_RECORDS` → that EIP
6. `deploy/bootstrap.sh` (packages, Caddy, `vidsense` user, repo, systemd)

It prints the **new public IP**. Update only `HostName` in `~/.ssh/config`
for `Host vidsense-dev` — `IdentityFile` stays `~/.ssh/vidsensed-dev.pem`.
The old EIP (`35.153.113.30`) is gone after destroy.

If SSH host-key warnings appear for `vidsense.info` or the old IP:

```bash
ssh-keygen -R vidsense.info
ssh-keygen -R <new-ip>
```

### 2. Restore state

Prefer the new Elastic IP (DNS TTL is 300s):

```bash
deploy/aws/restore-vm.sh --start deploy/aws/backups/vidsense-vm-<ts>.tar.gz <new-ip>
```

That writes `/opt/vidsense/data`, `/opt/vidsense/.env`, and
`/etc/caddy/Caddyfile`, then reloads Caddy and starts `vidsense`.

Without a backup, create a fresh `.env` from
[`docs/deployment-aws.md`](../../docs/deployment-aws.md) (required:
`APP_SECRET_KEY`, `YOUTUBE_API_KEY`, LLM keys, `APP_ALLOWED_HOSTS`,
`WEBSHARE_PROXY_*`) and configure Caddy basicauth.

### 3. Re-wire GitHub deploy

```bash
gh secret set SSH_HOST --env dev --body "<new-ip-or-vidsense.info>" --repo grigory93/vidsense
gh secret set SSH_USER --env dev --body "vidsense" --repo grigory93/vidsense
# SSH_PRIVATE_KEY: the *deploy* key (vidsense user), NOT vidsensed-dev.pem
# Optional: pin host keys from `ssh-keyscan -H <new-ip>`
# gh secret set SSH_KNOWN_HOSTS --env dev --repo grigory93/vidsense < known_hosts
```

Then uncomment the `push: branches: [main]` block in
`.github/workflows/deploy.yml` and merge.

### 4. Smoke test

```bash
curl -I http://vidsense.info
curl -u admin:<caddy-password> https://vidsense.info
```

Caddy issues Let’s Encrypt on first HTTPS hit (port 80 must be open, DNS
must already point at the new EIP).

---

## Keys and secrets

| Thing | Who it logs in as | Where it lives | Destroyed with the VM? |
|-------|-------------------|----------------|------------------------|
| `~/.ssh/vidsensed-dev.pem` | `ubuntu` (AMI / admin) | Your laptop + AWS key pair `vidsensed-dev` | No. `create.sh` reuses it. |
| GitHub `SSH_PRIVATE_KEY` | `vidsense` (deploy only) | GitHub Environment `dev` | No, but the VM `authorized_keys` is gone until you re-add the public half. |
| `/opt/vidsense/.env` | n/a | VM disk (and the backup tarball) | **Yes** unless backed up. Includes Webshare. |
| Caddy basicauth hash | n/a | `/etc/caddy/Caddyfile` | **Yes** unless backed up. |
| Webshare account | n/a | webshare.io dashboard | No. Subscription is independent of AWS. |

`~/.ssh/config` `Host vidsense-dev` should keep `IdentityFile
~/.ssh/vidsensed-dev.pem` and `User ubuntu`. After recreate, change
**only** `HostName` to the new Elastic IP.

---

## What still costs money after a freeze

- Route 53 hosted zone: I believe about **$0.50/month** per zone — verify on
  the [Route 53 pricing page](https://aws.amazon.com/route53/pricing/).
  `destroy.sh` never deletes the zone. Delete it in the console only if you
  want ~$0 and accept losing the DNS config.
- Domain registration (your registrar, not teardown).
- Any manual EBS snapshots or S3 backups you created.
- Webshare, if you keep that subscription.

Default VPC: free. Public IPv4 / EIP: billed only while allocated.

---

## Agent playbook

A later agent should treat this file as the procedure. Do not invent a
Terraform stack or a dedicated VPC. Do not skip backup.

### If the human says “freeze” / “tear down” / “stop paying”

1. Confirm `aws sts get-caller-identity` works. If not, ask them to run
   `aws sso login` in their terminal and wait.
2. Confirm `deploy/aws/config.env` exists. If not:
   `cp deploy/aws/config.example.env deploy/aws/config.env`
3. Run `deploy/aws/scan.sh`. Summarize the instance, EIP, and SG. Do not
   dump the raw JSON into chat.
4. Run `deploy/aws/backup-vm.sh`. Confirm the tarball lists `.env`, `data/`,
   and `Caddyfile`. Report whether Webshare keys are present (yes/no only).
5. Tell the human to copy `deploy/aws/backups/vidsense-vm-*.tar.gz` off the
   repo. **Wait until they confirm that copy exists.**
6. Remind them auto-deploy is already frozen. Optionally set `SSH_HOST=frozen`.
7. Run `deploy/aws/destroy.sh` only after they authorize destroy. It will
   prompt; they (or you, if they said to proceed) must type `yes`.
8. Re-run `deploy/aws/scan.sh us-east-1` and report that compute/EIP are gone.

### If the human says “recreate” / “bring the site back”

1. Confirm a backup tarball exists (local `backups/` or a path they provide).
2. Confirm `config.env` and `~/.ssh/vidsensed-dev.pem` exist.
3. Run `deploy/aws/create.sh`. Record the printed public IP. Do not start a
   second create if the first is still running.
4. Ask them to set `HostName` in `~/.ssh/config` to the new IP.
5. Run `deploy/aws/restore-vm.sh --start <archive> <new-ip>`.
6. Give them the GitHub secret commands and the smoke-test curls. Do not
   uncomment `deploy.yml` push trigger unless they asked to re-enable CD.
7. Never paste restored secrets.

### If you are blocked

- SSO expired → human runs `aws sso login`.
- SSH to the live VM fails → try `vidsense.info`, then the EIP, then
  `ssh vidsense-dev`. Check the SG still allows 22.
- `create.sh` cannot find an AMI → AWS API issue or wrong region; do not
  invent an AMI ID unless `scan.sh` showed a specific one to pin.
- Restore cannot SSH → use the **new** Elastic IP, not the old
  `35.153.113.30`. Run `ssh-keygen -R <host>` if host keys changed.

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---------|--------------|------------|
| `Token has expired` | AWS SSO idle timeout | `aws sso login` |
| `mapfile: command not found` | Old bug on macOS bash 3.2 | Already fixed via `read_lines_into` in `_lib.sh` |
| `backup-vm.sh` cannot SSH as `vidsense` | Wrong user | Default is `ubuntu` + `vidsensed-dev.pem` |
| Backup missing `.env` | Path not on the VM | Do not destroy. Inspect `/opt/vidsense` over SSH. |
| `create.sh` wants to overwrite the `.pem` | It will not | If AWS has the pair but the file is missing, restore the original `.pem` |
| Two instances after create | Old Name-tagged VM still up | `create.sh` now reuses by Name; `destroy.sh` first if you meant a clean rebuild |
| Site up but YouTube ingest fails | No Webshare on the new `.env` | Add `WEBSHARE_PROXY_*` from the backup or the Webshare dashboard |
| GitHub deploy fails after recreate | `SSH_HOST` still old IP / `frozen` | Update `dev` environment secrets; re-add deploy pubkey to `vidsense` `authorized_keys` |
| `destroy.sh` finds nothing | Untagged live VM + empty names | `config.env` must have `INSTANCE_NAME=vidsense-dev-t3med` and `SECURITY_GROUP_NAME=launch-wizard-3` |

---

## Related

- [`docs/aws-infra.md`](../../docs/aws-infra.md) — inventory snapshot, cost notes
- [`docs/deployment-aws.md`](../../docs/deployment-aws.md) — console / bootstrap checklist
- [`docs/deployment.md`](../../docs/deployment.md) — TLS, Caddy, Webshare
- [`deploy/bootstrap.sh`](../bootstrap.sh) — first-boot on a new VM
- [`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) — SSH CD (frozen on push)
