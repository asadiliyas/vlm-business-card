# Deployment Guide

Everything in this guide after "Phase 0" needs real AWS credentials, so it's
written to be run from **your own machine**, not by an AI assistant acting
on your behalf. Each phase says exactly what to run and what to expect.

Read `docs/ARCHITECTURE.md` first if you haven't — it explains *why* the
deployment is split into an app instance and a separate inference instance,
which this guide assumes.

---

## Phase 0 — AWS account setup (do this first; it has the longest lead time)

This phase has one especially important detail: **a brand-new AWS account's
GPU vCPU quota defaults to 0.** A `g4dn.xlarge` launch will be refused
outright until a Service Quotas increase is approved, and approval can take
anywhere from minutes to a few days. File the request immediately and do
everything else while it's pending — nothing later in this guide is
blocked on it (the CPU contingency path needs no quota at all).

1. **Create the account** at [aws.amazon.com](https://aws.amazon.com/), if
   you don't already have one.
2. **Enable MFA on the root user**, then create an IAM user with
   `AdministratorAccess` for day-to-day use instead of root. Install the AWS
   CLI and run `aws configure` with that IAM user's access key.
3. **Add a payment method.** Quota increase requests from accounts without
   one are routinely refused.
4. **Set a billing alarm before launching anything:**
   ```bash
   ./infra/scripts/billing-alarm.sh you@example.com 5
   ```
   This also prints a reminder to enable "Receive Billing Alerts" once in
   the Billing console (there's no CLI call for that specific checkbox).
5. **File the GPU quota request:**
   ```bash
   ./infra/scripts/request-gpu-quota.sh us-east-1
   ```
   Track approval status in the console under Service Quotas > Dashboard >
   Quota request history, or:
   ```bash
   aws service-quotas list-requested-service-quota-change-history --service-code ec2
   ```
6. Verify what credit/free-tier terms your account actually has under
   Billing > Credits — these change over time by signup promotion and
   region. See `docs/COSTS.md`.

**If the quota is rejected or still pending when you're ready to deploy,**
skip to "Alternative: CPU contingency path" below instead of waiting.

---

## Phase 1 — Push the code to GitHub

```bash
git remote add origin https://github.com/<you>/vlm-business-card.git
git push -u origin main
```

Update `REPO_URL` in `infra/scripts/provision-aws.sh` to match before
provisioning — the app instance clones from that URL on first boot.

---

## Phase 2 — Provision AWS resources

Open `infra/scripts/provision-aws.sh`, review the `CONFIG` block at the top
(region, instance types, your repo URL), then run it section by section (it
prints progress and a summary at the end):

```bash
./infra/scripts/provision-aws.sh
```

This creates, in order: an SSH key pair, two security groups (app tier open
on 80/443/22-from-you; inference tier open on 8000 *only from the app tier's
security group*, plus 22-from-you), the app instance with an Elastic IP
attached, and the GPU instance as a persistent spot request.

If the GPU step fails with a capacity/limit error, that's the quota from
Phase 0 not being approved yet — the app instance is still fully usable in
the meantime via the hosted fallback backend, and you can launch the CPU
contingency instance (below) or re-run just the GPU section once the quota
lands.

**Note the Elastic IP printed at the end** — you'll need it for the next
phase.

---

## Phase 3 — Configure and start the app tier

```bash
ssh -i vlm-card-key.pem ec2-user@<elastic-ip>
cd /opt/vlm-business-card
cp .env.example .env
nano .env   # or vi/vim
```

Fill in:
- `APP_DOMAIN` → `vlm-cards.<elastic-ip-with-dashes>.sslip.io` (e.g. an IP
  of `54.12.3.9` becomes `vlm-cards.54-12-3-9.sslip.io`) — this needs no DNS
  registration; sslip.io resolves it automatically.
- `VLM_PRIMARY_BASE_URL` → `http://<gpu-instance-private-ip>:8000/v1`
  (private IP, not public — the security group only allows the app tier to
  reach it, and using the private IP avoids the $0.005/hr public-IPv4 charge
  on that instance's traffic to the app)
- `VLM_FALLBACK_API_KEY` → a real DashScope or OpenRouter API key

Then:
```bash
docker compose up -d
docker compose logs -f app   # watch it come up; Ctrl+C to stop tailing
```

Caddy requests its TLS certificate automatically on first request to the
domain — the very first `https://` hit may take a few extra seconds while
that happens.

---

## Phase 4 — Start the inference tier

**GPU path** (if the quota was approved): the GPU instance already ran
`infra/scripts/gpu-instance-userdata.sh` on boot via Phase 2. Give it a few
minutes on first start — it downloads ~5–6 GB of model weights. Check
progress:
```bash
ssh -i vlm-card-key.pem ec2-user@<gpu-instance-public-ip>
docker logs -f qwen-vlm
```
Ready when `docker exec qwen-vlm curl -s localhost:8000/v1/models` returns
the model.

**CPU contingency path** (if the GPU quota wasn't approved in time): launch
a `t3.large` instead, using `infra/scripts/cpu-instance-userdata.sh` as its
user-data (same security group as the GPU instance would have used). It
needs no quota increase. Point `VLM_PRIMARY_BASE_URL` on the app instance at
this instance's private IP instead, and set
`VLM_PRIMARY_MODEL=qwen2.5-vl-3b-instruct-q4_k_m.gguf`. Expect 30–90s per
card rather than 2–5s.

---

## Phase 5 — Verify

```bash
curl https://vlm-cards.<elastic-ip-with-dashes>.sslip.io/api/health
```
Expect `"active_vlm_backend": "primary"` once the inference instance is up
(it'll correctly show `"fallback"` in the meantime if you've configured a
fallback API key — that's the fallback chain from `docs/ARCHITECTURE.md`
§2 working as designed, not a bug).

Open the URL in a browser, click **"Try a sample batch"**, and confirm
leads populate the table and the Excel export downloads correctly.

---

## Alternative: CPU contingency path from scratch

If you know upfront the GPU quota won't land in time (or want to avoid the
GPU cost entirely), skip the GPU step in Phase 2 and launch a `t3.large`
with `infra/scripts/cpu-instance-userdata.sh` instead, in the same
inference security group. Everything else in this guide is unchanged —
only `VLM_PRIMARY_BASE_URL`/`VLM_PRIMARY_MODEL` differ, per Phase 4 above.

---

## Redeploying after a code change

```bash
ssh -i vlm-card-key.pem ec2-user@<elastic-ip>
cd /opt/vlm-business-card
git pull
docker compose up -d --build
```

---

## Tearing down

When the deployment no longer needs to stay live (see `docs/COSTS.md` for
why this matters — a stopped instance's storage still bills):

```bash
./infra/scripts/teardown-aws.sh
```

Then double-check the EC2, Elastic IPs, Volumes, and Snapshots consoles —
the script only knows about resources it created under this project's
naming/tags.
