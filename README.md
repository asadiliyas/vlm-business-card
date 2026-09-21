# Business Card Lead Extractor

Upload a batch of business card photos, get back a structured, editable
lead list, and download it as Excel — extraction is powered by a
self-hosted **Qwen2.5-VL** vision-language model on AWS.

**Repository:** [github.com/asadiliyas/vlm-business-card](https://github.com/asadiliyas/vlm-business-card)
**Live app:** [https://vlm-cards.35-169-199-247.sslip.io](https://vlm-cards.35-169-199-247.sslip.io)
**Architecture & technical decisions:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
**Libraries, frameworks & models used:** [docs/COMPONENTS.md](docs/COMPONENTS.md)
**Cost estimate:** [docs/COSTS.md](docs/COSTS.md)
**Deployment walkthrough:** [docs/DEPLOY.md](docs/DEPLOY.md)

**Measured accuracy:** 100% (25/25 fields) on the bundled sample set,
verified end-to-end through the live deployment — see
[Measuring extraction accuracy](#measuring-extraction-accuracy) below for
how to reproduce this and why a larger, real-card set is the next step
before trusting this number broadly.

---

## What it does

1. Drag and drop (or click to browse) any number of business card images —
   JPEG, PNG, or WebP.
2. Each card is sent to a Qwen2.5-VL vision-language model with a prompt
   that extracts: **First Name, Last Name, Position/Job Title, Company,
   Location, Phone Number, Email Address** (plus a few bonus fields:
   additional phone numbers, website, a confidence score, and warning flags
   for anything uncertain).
3. Results stream into an editable table as each card finishes — click any
   cell to correct it before exporting.
4. Download the batch as a formatted `.xlsx` file at any point.
5. Uploaded images and extracted data are automatically deleted after a
   retention window (default 60 minutes) — see
   [docs/ARCHITECTURE.md §10](docs/ARCHITECTURE.md#10-privacy-and-retention).

A **"Try a sample batch"** button on the upload screen loads a few
synthetic sample cards so you can see the whole flow without needing real
business cards on hand.

## Architecture at a glance

```
Browser → Caddy (TLS) → FastAPI + React (EC2 t3.micro, free tier)
                                │
                    OpenAI-compatible /v1/chat/completions
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                     ▼
   vLLM + Qwen2.5-VL-7B-AWQ                Hosted Qwen (fallback)
   (EC2 g4dn.xlarge, spot — primary)       keeps the URL up if the
                                             GPU instance is down
```

The app tier and the inference tier are separate EC2 instances, because a
free-tier instance (1 GB RAM, no GPU) genuinely cannot run a VLM — see
[docs/ARCHITECTURE.md §1](docs/ARCHITECTURE.md#1-the-central-tension-qwen-vlm--free-tier-aws)
for the full reasoning, including the CPU-only contingency path that needs
no GPU quota at all.

## Repository layout

```
backend/          FastAPI app, VLM adapter, image pipeline, tests
  app/
    vlm/           OpenAI-compatible client + prompt + defensive JSON parser
    routers/       HTTP endpoints
    *.py            config, db, models, image pipeline, post-processing, export
  tests/           70 tests: unit + integration, VLM backend faked (no network needed)
  scripts/
    eval.py                    per-field accuracy harness against a labeled set
    generate_sample_cards.py   synthetic cards for the "try a sample batch" button
frontend/         React + TypeScript + Vite + Tailwind
infra/
  Caddyfile                    reverse proxy + automatic HTTPS
  scripts/                     AWS provisioning, quota request, billing alarm, teardown
docs/
  ARCHITECTURE.md              full design + every major technical decision
  COMPONENTS.md                every library/framework/model used, and why
  COSTS.md                     detailed cost breakdown
  DEPLOY.md                    step-by-step AWS deployment guide
docker-compose.yml  App + Caddy, run on the app EC2 instance
Dockerfile           Multi-stage build: frontend assets + Python runtime
```

## Local development

### Backend

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate        # Windows: .venv\Scripts\activate — macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then fill in a VLM_FALLBACK_API_KEY to actually extract data
uvicorn app.main:app --reload --port 8000
```

Without any VLM backend configured, the app still runs correctly end to
end — uploads are accepted, images are validated and stored, and each card
is cleanly marked `failed` with a clear error rather than the server
crashing (this is the primary/fallback chain exhausting itself; see
[docs/ARCHITECTURE.md §2](docs/ARCHITECTURE.md#2-primaryfallback-vlm-backend-chain)).
Set `VLM_FALLBACK_API_KEY` to a real
[DashScope](https://dashscope.console.aliyun.com/) or
[OpenRouter](https://openrouter.ai/) key to see real extractions locally.

Run the tests:
```bash
python -m pytest -v
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` — API calls are proxied to `localhost:8000`
(see `frontend/vite.config.ts`), so run the backend alongside it.

### Both together, in Docker

```bash
cp .env.example .env    # repo root — fill in a VLM_FALLBACK_API_KEY at minimum
docker compose up --build
```
Set `APP_DOMAIN=localhost` in `.env` first. Caddy detects that as a
non-public name and serves it over HTTPS with a locally-trusted certificate
instead of requesting a real one — open `https://localhost` (or
`curl -k`) to accept it. The `app` container itself isn't published to the
host on purpose (Caddy is the only public entry point, matching
production); for a faster inner loop without Docker at all, use the
backend + frontend dev servers above instead.

**Optional — fully local, no cloud API key needed:** run
```bash
docker compose --profile cpu-inference up --build
```
This additionally starts Qwen2.5-VL-3B on llama.cpp locally (CPU) and the
default `.env.example` `VLM_PRIMARY_BASE_URL` already points at it. First
start downloads ~2 GB of model weights.

## Measuring extraction accuracy

```bash
cd backend
python scripts/eval.py --dataset ../sample_cards    # the bundled synthetic set + labels.json
```
Reports per-field accuracy (first/last name, job title, company, location,
phone, email) against a labeled `labels.json`. The bundled synthetic set
(`sample_cards/`, also used by the frontend's "try a sample batch" button)
is a pipeline smoke test, not a representative accuracy number — it's
clean, flat, printed text with no glare, rotation, or handwriting. Point
`--dataset` at a folder of real photographed cards instead (same format:
image files + a `labels.json` — `scripts/generate_sample_cards.py` shows
the exact shape it expects) for a number worth quoting.

## Deploying to AWS

Full walkthrough, including the AWS account setup and the GPU quota request
every new account needs: **[docs/DEPLOY.md](docs/DEPLOY.md)**.

## Environment variables

See [backend/.env.example](backend/.env.example) (running the backend
directly) and [.env.example](.env.example) (running via `docker compose`,
repo root) — every variable is documented inline. The short version: point
`VLM_PRIMARY_*` at a self-hosted Qwen2.5-VL endpoint and `VLM_FALLBACK_*`
at a hosted one; both speak the same OpenAI-compatible API.

## Testing

```bash
cd backend && python -m pytest -v
cd frontend && npm run build   # TypeScript strict-mode check + production bundle
```
CI (`.github/workflows/ci.yml`) runs both, plus a Docker build, on every
push.

## Known limitations / what I'd improve with more time

- **The fallback VLM backend is best-effort, not verified-reliable.** The
  primary (self-hosted Qwen2.5-VL, currently on the CPU contingency path
  — see below) is fully verified at 100% field accuracy on the test set.
  The hosted fallback is configured and will engage automatically the
  moment the primary is unavailable, but two external constraints hit
  during deployment mean it isn't dependable today: DashScope doesn't
  currently accept registrations from this account's country, and
  OpenRouter throttles vision (not text) requests hard for accounts with
  no payment history. Full detail and reasoning in
  [docs/ARCHITECTURE.md §2](docs/ARCHITECTURE.md#2-primaryfallback-vlm-backend-chain).
  With more time: either a payment-history-bearing OpenRouter account, or
  a DashScope account registered from a supported country, would make
  this fully reliable with no code changes — the adapter already supports
  either.
- **Running on the CPU contingency path, not the GPU path, at submission
  time.** A brand-new AWS account's GPU vCPU quota defaults to 0; the
  increase was requested on day one but AWS's approval can take longer
  than this project's timeline. The CPU path (Qwen2.5-VL-3B on a
  free-tier-eligible instance) is fully functional — verified at 100%
  accuracy — just slower per card (tens of seconds vs. single digits on
  GPU). The architecture is designed so this is a config change, not a
  rewrite, once the quota clears.
- **No authentication.** Reasonable for a single-reviewer take-home
  submission; a real internal tool would add it.
- **Single SQLite instance, no horizontal scaling.** Appropriate at this
  scale (see [docs/ARCHITECTURE.md §5](docs/ARCHITECTURE.md#5-why-fastapi--sqlite-instead-of-a-heavier-stack)
  for the reasoning); Postgres + a real job queue would be the next step
  if usage ever demanded it.
- **The accuracy number (100%) is on a small, synthetic sample set** (4
  cards, clean and flat, no glare/rotation/handwriting) — a pipeline
  correctness check, not a claim about real-world photographed cards. The
  eval harness (`backend/scripts/eval.py`) is built to run against a
  larger, real-card set; I'd build that set with more time.
- **Mobile layout was implemented deliberately** (a responsive card view
  replaces the results table below tablet width) but I don't have a way
  to screenshot it myself to confirm the visual result — worth a spot
  check on an actual device.

## AI Usage

This project was built with **Claude Code** (Anthropic's agentic CLI,
running Claude Opus 5 / Sonnet 5) as the primary development tool, used
end to end: architecture and prompt design, the full FastAPI backend and
React frontend, the AWS infrastructure (provisioned via CLI — EC2,
security groups, Elastic IP, Service Quotas, Budgets/CloudWatch alarms),
live deployment and debugging against the real running system, and the
UI redesign pass.

**What I did, and what the AI did:** I set direction and made the calls
that were mine to make — the primary/fallback deployment strategy and
its cost trade-offs, which hosted-Qwen provider to sign up for, when to
proceed past a cost checkpoint, rejecting and redirecting the first UI
color scheme, and verifying the live app myself in the browser at each
stage. Claude Code wrote the implementation, ran the AWS CLI commands
against my credentials, SSH'd into the instances to configure and debug
them, and iterated based on what real testing against the live deployment
actually showed — including diagnosing and fixing real bugs found only by
testing against production (a job-orphaning race condition on container
restart, a concurrency/timeout mismatch that broke bulk uploads under
real load, a mislabeled Hugging Face model repo, and a Docker healthcheck
pointed at the wrong port). I reviewed the results at each step rather
than accepting them sight unseen — through the running application, the
extracted data, and the exported files.

**Adopted:** the primary/fallback VLM adapter design (one client, backend
swappable by config, so a stopped GPU instance or an AWS quota delay never
takes the app down); the defensive JSON-parsing layer for VLM output
(models reliably wrap JSON in markdown fences or add stray text despite
instructions not to); the retention/PII-minimization approach for
uploaded card images; the concurrency and timeout values, which were
tuned to real numbers measured against the live inference server rather
than left at initial guesses.

**Rejected or changed:** the first version of the frontend used a
default indigo/violet color scheme, which read as a generic
AI-scaffolded template rather than a considered design — I rejected it
and asked for a different, more deliberate palette. Claude's first
attempt at a hosted-Qwen fallback (via DashScope) turned out to be
blocked by account-country availability, and a follow-up attempt
(OpenRouter's free tier) turned out to be unreliable for vision requests
on a zero-payment-history account; rather than accept either as "done,"
I asked for direct verification (which surfaced both issues honestly)
and for the limitation to be documented plainly instead of overstated —
see "Known limitations" above.

## License

MIT — see [LICENSE](LICENSE).
