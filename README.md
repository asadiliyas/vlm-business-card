# Business Card Lead Extractor

Upload a batch of business card photos, get back a structured, editable
lead list, and download it as Excel — extraction is powered by a
self-hosted **Qwen2.5-VL** vision-language model on AWS.

**Live app:** _add the deployed URL here once Phase 2–5 of
[docs/DEPLOY.md](docs/DEPLOY.md) are complete_
**Architecture & technical decisions:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
**Libraries, frameworks & models used:** [docs/COMPONENTS.md](docs/COMPONENTS.md)
**Cost estimate:** [docs/COSTS.md](docs/COSTS.md)
**Deployment walkthrough:** [docs/DEPLOY.md](docs/DEPLOY.md)

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

## License

MIT — see [LICENSE](LICENSE).
