# Assignment 1 — VLM Business Card Lead Extraction
## Build & Deployment Plan

---

## 0. The one real constraint to resolve first

The assignment says "deploy a Qwen VLM on a free-tier or equivalent AWS environment." Those two
things are in tension, and the whole architecture hangs off how we resolve it:

- AWS free-tier compute is `t2.micro` / `t3.micro` — **1 GB RAM, 2 vCPU, no GPU**.
- The smallest useful Qwen VLM (`Qwen2.5-VL-3B-Instruct`, 4-bit GGUF) needs **~4–6 GB RAM**
  just to load weights + vision projector, before any image context.

A Qwen VLM cannot run inside a 1 GB free-tier box. Any submission that claims otherwise is either
not running Qwen or not running on free tier. We resolve this honestly by **splitting the app tier
from the inference tier**, and making the inference tier a pluggable adapter.

### Deployment options (pick one as primary — see "Decisions needed")

| | Option A — CPU self-host | Option B — GPU self-host | Option C — Hosted Qwen API |
|---|---|---|---|
| **Model** | Qwen2.5-VL-3B-Instruct (Q4_K_M GGUF) | Qwen2.5-VL-7B-Instruct-AWQ | Qwen2.5-VL 7B / 72B |
| **Server** | `llama.cpp` `llama-server` | `vLLM` | DashScope / OpenRouter |
| **Host** | EC2 `t3.large` (8 GB) | EC2 `g4dn.xlarge` (T4 16 GB) | n/a |
| **Cost** | ~$0.083/hr on-demand, ~$0.03 spot | ~$0.53/hr on-demand, ~$0.16 spot | free-tier quota |
| **Latency/card** | 30–90 s | 2–5 s | 3–8 s |
| **"Qwen deployed on AWS"?** | Yes, fully | Yes, fully | No — weakest for grading |
| **Batch of 50 cards** | ~45 min (painful) | ~3 min | ~5 min |

**DECIDED: B is primary, C is the automatic fallback, A is the documented contingency.**

We build the adapter so all three work. Qwen2.5-VL-7B-AWQ runs on vLLM on a `g4dn.xlarge` spot
instance; if that instance is stopped (or its GPU quota is still pending), the app transparently
falls back to a hosted Qwen endpoint so the public URL never 500s. `GET /api/health` reports which
backend is live, so the fallback is visible rather than hidden. The README states this plainly:
"Qwen2.5-VL is self-hosted on EC2 g4dn; a hosted-Qwen fallback keeps the demo URL available when
the GPU instance is scheduled down."

All three speak the **OpenAI-compatible `/v1/chat/completions` protocol with image content parts**,
so a single client adapter covers all of them. This is the most important technical decision in the
project — it de-risks everything downstream.

---

## 1. Target architecture

```
                        +------------------------------------------+
  Browser               |  EC2 t3.micro (free tier) - always on    |
  +------------+        |  +------------------------------------+  |
  | React SPA  |<------>|  | Caddy (TLS, Let's Encrypt)         |  |
  |  dropzone  |  HTTPS |  +---------------+--------------------+  |
  |  table     |        |                  | reverse proxy         |
  |  export    |        |  +---------------v--------------------+  |
  +------------+        |  | FastAPI (uvicorn)                  |  |
                        |  |  - upload + validation             |  |
                        |  |  - async job queue (semaphore)     |  |
                        |  |  - image preprocess (Pillow)       |  |
                        |  |  - VLM adapter --------------+     |  |
                        |  |  - schema validation (Pydantic)|    |  |
                        |  |  - normalization (phonenumbers)|    |  |
                        |  |  - XLSX export (openpyxl)      |    |  |
                        |  |  - SQLite (jobs, leads)        |    |  |
                        |  +--------------------------------+----+  |
                        +-----------------------------------+-------+
                                                            | OpenAI-compatible
                                    +-----------------------+--------------+
                                    |                                      |
                        +-----------v-----------+   fallback  +------------v-----------+
                        | EC2 g4dn.xlarge       |------------>| Hosted Qwen API        |
                        | vLLM + Qwen2.5-VL-7B  |             | (DashScope/OpenRouter) |
                        | (SG locked to app)    |             +------------------------+
                        +-----------------------+
```

### Request flow
1. User drops N images → `POST /api/jobs` (multipart) → returns `job_id`, status `queued`.
2. Background worker processes files with bounded concurrency (`asyncio.Semaphore`, 2–6).
3. Per file: EXIF-orient → downscale to 1280px long edge → JPEG q85 → base64 data URL.
4. One VLM call per card with a strict JSON-schema prompt; response parsed and repaired.
5. Post-process: name split, phone → E.164, email validation, location normalize, confidence flags.
6. Row persisted to SQLite; frontend polls `GET /api/jobs/{id}` (or SSE) and streams rows in.
7. User edits any cell inline → `PATCH /api/leads/{id}`.
8. `GET /api/jobs/{id}/export.xlsx` streams a styled workbook.

---

## 2. Tech stack

**Backend**
- Python 3.12, FastAPI, uvicorn
- Pydantic v2 — the extraction schema *is* the contract
- Pillow — EXIF transpose, downscale, JPEG re-encode, thumbnails
- `httpx` (async) — VLM client
- `phonenumbers` (Google libphonenumber) — phone normalization to E.164
- `email-validator` — email syntax sanity
- `nameparser` — title/first/middle/last/suffix splitting ("Dr. Jane R. Smith-Okoye, PhD")
- `openpyxl` — styled XLSX export
- SQLite via `aiosqlite` — jobs + leads, no external DB to provision
- `python-multipart`, `slowapi` (rate limiting)

**Frontend**
- React 18 + TypeScript + Vite
- Tailwind CSS, hand-rolled components (keeps the bundle small on a t3.micro)
- `react-dropzone` — bulk drag & drop
- TanStack Table — editable results grid
- Built to static assets served by FastAPI (single origin, no CORS, one container)

**Inference**
- `Qwen/Qwen2.5-VL-7B-Instruct-AWQ` on vLLM (GPU), **or**
- `Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` + `mmproj` on `llama.cpp` (CPU)
- Both exposed as OpenAI-compatible endpoints

**Infra**
- Docker + docker compose (app; inference behind a compose profile)
- Caddy for automatic HTTPS
- Public hostname: `sslip.io` / `nip.io` wildcard DNS against the elastic IP (zero cost, real TLS),
  or a real domain if you have one
- GitHub Actions: lint + test on push; deploy over SSH on tag (nice-to-have)

---

## 3. The extraction schema (the core contract)

```python
class Lead(BaseModel):
    first_name:  str | None
    last_name:   str | None
    job_title:   str | None
    company:     str | None
    location:    str | None   # "City, State, Country", normalized
    phone:       str | None   # primary, E.164
    email:       str | None
    # --- beyond the required 7, kept for quality + debuggability ---
    additional_phones: list[str] = []
    website:     str | None
    raw_text:    str | None    # full OCR dump, for audit and manual recovery
    confidence:  float
    warnings:    list[str] = []  # "no_email_found", "ambiguous_name", ...
```

### Prompting strategy
- System prompt pins the model to **JSON only**, with the schema inline and explicit rules:
  - `company` is the organization, **not** the tagline or slogan
  - `location` collapses a multi-line postal address to City, State/Region, Country
  - if the card shows several phones, `phone` = mobile/direct; the rest go to `additional_phones`
  - never invent a value — use `null`
- Two-stage fallback for hard cards: if JSON parsing fails or `confidence` is below threshold,
  re-ask with a "transcribe every line verbatim first, then fill the JSON" variant.
- Temperature 0; `response_format: json_object` where the backend supports it.

### Known-hard cases we handle explicitly
- Double-sided cards (front + back of the same person) → optional client-side pairing
- Non-Latin / bilingual cards (Qwen2.5-VL is strong at CJK and Arabic — worth showcasing)
- Rotated, skewed, low-light phone photos → EXIF handling + optional deskew
- Company-only cards with no person → empty name, still a valid row
- Multiple people on one card → take the primary contact and emit a warning

---

## 4. Work breakdown

### Phase 0 — AWS account + GPU quota (DAY ONE — longest lead time, blocks nothing else)

This is the critical path. **A brand-new AWS account has a GPU vCPU quota of 0**, so a
`g4dn.xlarge` launch is refused outright until a quota increase is approved. Approval commonly
takes hours to a few days, and first requests from accounts with no billing history are sometimes
refused. Everything else in this plan proceeds in parallel against a hosted backend, so a slow
approval costs us nothing as long as we file it immediately.

- [ ] Create the AWS account; enable MFA on root; create an IAM admin user and stop using root
- [ ] Add a payment method (quota requests from accounts without one are routinely refused)
- [ ] **Set a billing alarm at $5 and a zero-spend budget alert before launching anything**
- [ ] Pick a region with good `g4dn` capacity — `us-east-1` or `us-west-2`
- [ ] File Service Quotas increases in that region:
      - `All G and VT Spot Instance Requests` → **4 vCPUs** (this is the one we need for spot)
      - `Running On-Demand G and VT instances` → **4 vCPUs** (contingency if spot capacity is short)
- [ ] Create an EC2 key pair; note the account/region for the deploy scripts
- [ ] Install and configure the AWS CLI locally (not currently on this machine)

**Contingency if the quota is refused or still pending at submission time:** fall back to Option A
(`t3.large` CPU + llama.cpp) — a non-GPU instance needs no quota increase and is still a genuine
self-hosted Qwen deployment. The adapter makes this a config change, not a rewrite.

### Phase 1 — Repo skeleton and contracts
- [ ] `git init`, `.gitignore`, license, layout (`backend/`, `frontend/`, `infra/`, `docs/`)
- [ ] Pydantic `Lead` / `Job` models, OpenAPI-visible response schemas
- [ ] `settings.py` (pydantic-settings): `VLM_BACKEND`, `VLM_BASE_URL`, `VLM_MODEL`, `VLM_API_KEY`,
      `MAX_FILES`, `MAX_FILE_MB`, `CONCURRENCY`, `RETENTION_MINUTES`
- [ ] `.env.example`

### Phase 2 — VLM adapter and prompt (highest risk — do it first)
- [ ] `vlm/client.py` — one async OpenAI-compatible client, backend-agnostic
- [ ] `vlm/prompts.py` — system + user prompt, schema in prompt
- [ ] `vlm/parse.py` — JSON extraction from fenced/noisy output, repair pass, Pydantic validation
- [ ] Retry with exponential backoff, per-call timeout, graceful degradation to fallback backend
- [ ] **Bench it against real cards before building any UI**

### Phase 3 — Image pipeline
- [ ] Validate MIME by magic bytes (not extension); cap size and count; reject non-images
- [ ] EXIF transpose, downscale long edge to 1280, JPEG q85, strip metadata
- [ ] 256px thumbnails for the results table
- [ ] Temp storage with a TTL sweeper — business cards are PII, we do not hoard them

### Phase 4 — Job engine and API
- [ ] SQLite schema + migrations (plain SQL; Alembic is overkill here)
- [ ] `POST /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/stream` (SSE),
      `PATCH /api/leads/{id}`, `DELETE /api/jobs/{id}`, `GET /api/health`
- [ ] Bounded-concurrency worker, per-file status (`queued|processing|done|failed`)
- [ ] Partial-failure semantics — one bad card must not sink the batch

### Phase 5 — Post-processing and normalization
- [ ] `nameparser` split, with heuristics when the model returns a single `full_name`
- [ ] `phonenumbers` → E.164, region inferred from the card's country/location
- [ ] Email lowercasing, validation, common OCR-typo repair (`@gmall.com` → flag)
- [ ] Location normalization; company kept verbatim, only trimmed
- [ ] Duplicate detection across the batch (same email/phone → flag, never auto-merge)

### Phase 6 — Frontend
- [ ] Dropzone with multi-file and folder drop, client-side preview and size guardrails
- [ ] Live progress: per-file status chips, overall progress bar, streaming row insert
- [ ] Editable results table (all 7 fields), thumbnail column, warning badges, row delete
- [ ] "Export to Excel" and "Clear batch" (privacy)
- [ ] Empty / error / loading states; usable on mobile
- [ ] Sample-cards button so a reviewer can try it without hunting for images

### Phase 7 — Excel export
- [ ] `openpyxl`: bold frozen header, auto column widths, **text-formatted phone column** (stops
      Excel mangling numbers into scientific notation), hyperlinked emails, autofilter
- [ ] Columns: First Name, Last Name, Position/Job Title, Company, Location, Phone, Email,
      plus Source File and Confidence
- [ ] Streamed response, `Content-Disposition: attachment; filename=leads_YYYY-MM-DD.xlsx`

### Phase 8 — Hardening
- [ ] Per-IP rate limiting, max batch size, request body cap at the Caddy layer too
- [ ] Structured logging with request IDs, no PII in logs
- [ ] Global exception handler → clean JSON errors, never a stack trace to the client
- [ ] Retention sweeper: delete images and rows after N minutes, stated in the UI footer

### Phase 9 — Containerization and deploy
- [ ] Multi-stage `Dockerfile` (node build → python runtime), non-root user, healthcheck
- [ ] `docker-compose.yml` with a `cpu-inference` profile to optionally run llama.cpp locally
- [ ] `infra/` — EC2 user-data bootstrap, security groups, `Caddyfile`
- [ ] Provision EC2 + elastic IP, deploy, TLS via Caddy, verify the public URL end to end
- [ ] If GPU option: separate inference instance, SG locked to the app instance only,
      start/stop schedule, fallback wiring verified by stopping the box

### Phase 10 — Documentation and submission
- [ ] `README.md` — what it does, screenshots, local setup, env vars, Docker run, AWS deploy
      step by step, troubleshooting
- [ ] `docs/ARCHITECTURE.md` — diagram, request flow, **major technical decisions and their
      trade-offs** (explicitly graded)
- [ ] `docs/COMPONENTS.md` — every library, framework, pretrained model and external service, with
      version, license and rationale
- [ ] Final pass against the 6 functional requirements and 5 submission requirements

### Phase 11 — Testing (woven through, not bolted on)
- [ ] Unit: JSON repair, name splitting, phone normalization, XLSX bytes
- [ ] Integration: fake VLM backend → full job lifecycle → export
- [ ] A small labeled eval set (10–20 cards including hard ones) and `scripts/eval.py` reporting
      per-field accuracy. **This is the differentiator** — it turns "it seems to work" into a number
      we can put in the README.

---

## 5. Deliverables → requirement mapping

| Requirement | Delivered by |
|---|---|
| 1. Qwen VLM deployed on AWS free-tier/equivalent | Phases 2 + 9; documented honestly in ARCHITECTURE.md |
| 2. Bulk upload of business card images | Phase 6 dropzone, Phase 4 `POST /api/jobs` |
| 3. Structured lead list (7 fields) | Phase 2 schema + Phase 5 normalization |
| 4. Display leads in-app | Phase 6 editable table |
| 5. Download as Excel | Phase 7 |
| 6. Public URL | Phase 9 |
| Git repo / source package | Phase 1 (git from commit #1) |
| README with setup + deploy | Phase 10 |
| Architecture + technical decisions | `docs/ARCHITECTURE.md` |
| Libraries / frameworks / models used | `docs/COMPONENTS.md` |

---

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| CPU inference too slow for a live demo | Cap batch size in UI, show progress, offer GPU profile, pre-warm the model |
| Model returns malformed JSON | Repair pass + retry with stricter prompt + Pydantic validation gate |
| Inference box down at review time | Automatic hosted-Qwen fallback; `/api/health` reports the active backend |
| AWS cost overrun | Spot instances, billing alarm at $5, stop schedule, documented teardown |
| Free-tier RAM exhaustion on t3.micro | 2 GB swap in user-data; the app tier is light (no model in-process) |
| PII handling | TTL deletion, no PII in logs, HTTPS only, clear-batch button, stated retention policy |
| Reviewer cannot test it | Bundled sample cards and a one-click "try sample batch" |
| **GPU quota not approved in time** | Filed day one (Phase 0); hosted fallback keeps the URL live; Option A needs no quota |
| Spot instance reclaimed mid-demo | Fallback backend absorbs it automatically; on-demand quota requested as backup |
| New-account credits exhausted | Billing alarm at $5, instance stopped outside demo windows, teardown documented |

---

## 7. Decisions locked in

| Decision | Choice | Consequence |
|---|---|---|
| Primary inference | **B — vLLM + Qwen2.5-VL-7B-AWQ on EC2 `g4dn.xlarge` spot** | Needs a GPU quota increase (Phase 0). 2–5 s/card. |
| Fallback inference | **C — hosted Qwen endpoint**, automatic | Public URL stays up when the GPU box is stopped |
| Contingency | **A — `t3.large` + llama.cpp**, documented | No quota needed; config change, not a rewrite |
| App tier | EC2 `t3.micro` free tier, always on | Holds the public URL and the elastic IP |
| AWS account | **To be created** | Phase 0 is day-one work; MFA, IAM user, billing alarm |
| Public URL | `sslip.io` against the elastic IP, TLS via Caddy | Zero cost, real HTTPS, no DNS registrar needed |
| Source delivery | **Public GitHub repo** | Clean commit history from commit #1 is part of the submission |

## 8. Build order

Phase 0 runs first and then runs *in the background* — the quota request is asynchronous, so we
start Phase 1 the same day and develop the entire application against the hosted Qwen backend
(Option C). The GPU instance gets wired in at Phase 9, by which point it is a URL and a model name
in a config file. Nothing in Phases 1–8 depends on the quota being approved.

The first real build step is Phase 2, not the UI: **prove the Qwen prompt extracts all seven fields
correctly from real cards before writing a single React component.** If the extraction quality is
not there, everything built on top of it is wasted effort.
