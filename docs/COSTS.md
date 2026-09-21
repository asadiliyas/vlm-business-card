# Cost Estimate

**Expected out-of-pocket cost to build and submit this project: $0**, covered
by AWS's new-account signup credits — conditional on the guardrails in this
document actually being followed. This is not a guarantee; read the caveats.

## Line items (us-east-1, one month, primary GPU path)

| Item | Rate | Assumption | Cost |
|---|---|---|---|
| App tier — EC2 `t3.micro` | $0.0104/hr | 24/7, 730 hrs | $7.59 |
| EBS gp3, 30 GB (app) | $0.08/GB-mo | 1 month | $2.40 |
| Elastic IP (app, attached) | $0.005/hr | 730 hrs | $3.65 |
| GPU tier — `g4dn.xlarge` **spot** | ~$0.16/hr | 30 hrs (setup + testing + demo windows) | $4.80 |
| EBS gp3, 75 GB (GPU: CUDA + model weights) | $0.08/GB-mo | 1 month | $6.00 |
| Public IPv4 on GPU instance, while running | $0.005/hr | 30 hrs | $0.15 |
| Data transfer out | 100 GB/mo free | ~1 GB | $0 |
| Hosted Qwen API (dev + fallback) | free quota | ~2,000 images | $0 |
| `sslip.io` DNS | — | — | $0 |
| Public GitHub repo | — | — | $0 |
| **Total** | | | **≈ $24.60** |

Against typical new-account signup credits, this lands at **$0 paid**. Even
leaving the GPU instance running 24/7 for two full weeks instead of ~30
hours (336 hrs × $0.16 ≈ $54) keeps the total under $70.

## Two line items that surprise people

- **EBS bills while an instance is stopped.** The 75 GB volume holding CUDA
  and the model weights costs ~$6/month whether or not the GPU instance is
  running. *Stopped* is not the same as *not billing*. Terminating the
  instance (not just stopping it) is what actually stops this — see
  `infra/scripts/teardown-aws.sh`.
- **Public IPv4 addresses are no longer free.** Since February 2024, every
  public IPv4 — including an attached Elastic IP — costs $0.005/hr. This is
  why only the app tier gets a (stable) Elastic IP; the GPU instance uses
  an auto-assigned public IP that's released the moment it stops.

## What could actually cost real money

**Launching `g4dn.xlarge` on-demand instead of spot, and forgetting about
it.** On-demand is $0.526/hr — **$384 for a month** left running. This one
mistake dwarfs everything else in this document combined. It's exactly what
`infra/scripts/billing-alarm.sh` (a CloudWatch alarm + Budget at a low
threshold, set up *before* any instance launches) exists to catch.

The other classic: teardown debris. An unattached Elastic IP ($3.65/mo) or
an orphaned EBS volume/snapshot billing quietly after you think you're
done. `infra/scripts/teardown-aws.sh` walks through releasing/deleting each
of these in order.

## Cost vs. requirement-1 fidelity — the honest trade-off

| Path | Monthly cost | Satisfies "deploy a Qwen VLM on AWS"? |
|---|---|---|
| **B — GPU spot (this project's primary path)** | ~$25, covered by credits | Yes, fully |
| **A — CPU contingency (`t3.large` + llama.cpp)** | ~$10–15 | Yes, fully — slower per card |
| **C — hosted Qwen API only, no self-hosted instance** | $0, hard guarantee | No — this calls a Qwen API rather than deploying one |

Path B was chosen as primary specifically because it's the only option that
fully satisfies requirement #1 while still landing at $0 under typical
signup credits (see `docs/ARCHITECTURE.md` §1–3 for the technical reasoning
and the automatic fallback that keeps the URL alive if B is ever
unavailable).

## Caveat

AWS's free-tier/credit offering for new accounts changes over time — the
exact credit amount, duration, and eligibility depend on the signup
promotion and region active when the account was created. **Verify the
actual credit grant on the account's Billing console before relying on
this estimate**, and re-run the numbers above against path A if it's
materially smaller than assumed here.

## After submission: the cost that isn't "during the project"

Credits eventually expire (commonly ~6 months), but a deployed instance
keeps running and billing your card regardless. A `t3.micro` + ~100 GB of
EBS + an Elastic IP left running indefinitely is roughly **$18/month**
quietly billing after the credits are gone. Put a reminder to run
`infra/scripts/teardown-aws.sh` (or at least review the AWS Billing
console) once the submission has been reviewed and the live URL is no
longer needed.
