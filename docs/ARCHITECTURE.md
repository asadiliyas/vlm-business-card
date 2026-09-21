# Architecture & Technical Decisions

This document explains how the system is put together and, more importantly,
*why* — the assignment asks specifically for major technical decisions, so
each section below leads with the decision and the trade-off it resolves.

## 1. The central tension: "Qwen VLM" + "free-tier AWS"

The assignment asks for a Qwen vision-language model deployed on a
free-tier or equivalent AWS environment. Those two requirements are in
direct tension:

- AWS free tier means a `t2.micro`/`t3.micro` instance: **1 GB RAM, 2 vCPU,
  no GPU.**
- The smallest usable Qwen VLM, `Qwen2.5-VL-3B-Instruct` at 4-bit
  quantization, needs **roughly 4–6 GB of RAM** just to hold its weights
  and vision projector — before it has processed a single image.

A Qwen VLM cannot run inside a 1 GB instance. Rather than paper over that
(e.g. quietly calling a hosted API and describing it as "deployed"), the
architecture makes the tension explicit and resolves it honestly:

**The application tier and the inference tier are two separate EC2
instances**, sized for what they each actually do:

| Tier | Instance | Why |
|---|---|---|
| App (this repo: FastAPI + React) | `t3.micro`, **free-tier eligible** | Serves static assets and thin JSON endpoints — genuinely fits in 1 GB |
| Inference (Qwen2.5-VL) | `g4dn.xlarge` (GPU, primary, pending quota) or a free-tier-eligible CPU instance (contingency, currently live) | Actually holds and runs model weights |

The GPU path is not free-tier, but it **is a real, self-hosted Qwen
deployment on AWS**, run on a spot instance to keep cost minimal (see
`docs/COSTS.md`). This satisfies requirement #1 truthfully instead of
technically.

**A deployment-time discovery worth recording:** this account was created
under AWS's newer credit-based "Free Plan" (see `docs/COSTS.md`), which
turned out to have a broader free-tier-eligible instance list than the
classic `t2/t3.micro`-only free tier — including `m7i-flex.large`
(2 vCPU, **8 GB RAM**). That's enough to run Qwen2.5-VL-3B-Instruct at Q4
quantization comfortably, which means the CPU contingency path described
below is, on this account, not just cheap but **genuinely free** —
narrowing the "Qwen VLM" vs. "free-tier AWS" tension further than the
original plan assumed. (This is account/promotion-dependent, not a
platform guarantee — see the note in `docs/DEPLOY.md` on checking a given
account's actual free-tier-eligible list before assuming an instance type.)

## 2. Primary/fallback VLM backend chain

**Decision:** the backend never talks to exactly one inference endpoint. It
tries a *primary* backend first and automatically falls over to a
*fallback* backend on any failure — connection refused, timeout, HTTP
error, or repeated unparseable output.

```
                    ┌─────────────────────────┐
   image  ────────► │       VLMClient          │
                    │  1. try PRIMARY          │──── vLLM + Qwen2.5-VL-7B-AWQ
                    │     (retry + backoff)     │     on EC2 g4dn.xlarge spot
                    │  2. on failure, try       │
                    │     FALLBACK              │──── Hosted Qwen (DashScope /
                    └─────────────────────────┘     OpenRouter)
```

**Why this matters more than it might look:** a spot GPU instance can be
reclaimed by AWS at any time, and a GPU quota request on a new AWS account
can take days to approve (see `docs/DEPLOY.md` Phase 0). Without a
fallback, either of those would take the entire public demo offline. With
it, `GET /api/health` reports which backend is actually live, and the
person reviewing this submission sees a working app even if the spot
instance happens to be down at that exact moment.

**Why this was cheap to build:** vLLM, llama.cpp's `llama-server`, AWS
Bedrock-style hosts, DashScope, and OpenRouter all speak the same
**OpenAI-compatible `/v1/chat/completions` protocol** with image content
parts. One client (`backend/app/vlm/client.py`) drives all of them —
switching backends is a config change (base URL, model name, API key), not
a rewrite. This is also what makes the CPU contingency path (below) nearly
free to support.

## 3. GPU primary, CPU contingency, hosted fallback — three deployment paths, one adapter

A brand-new AWS account's GPU vCPU quota defaults to **0**. A
`g4dn.xlarge` launch is refused outright until a Service Quotas increase is
approved, which can take hours to days (see `docs/DEPLOY.md`). Rather than
block the whole project on that approval:

| Path | Model / server | Needs GPU quota? | Latency/card |
|---|---|---|---|
| **Primary** | Qwen2.5-VL-7B-Instruct-AWQ on vLLM, `g4dn.xlarge` spot | Yes | 2–5s |
| **Contingency** (currently live) | Qwen2.5-VL-3B-Instruct (Q4_K_M GGUF, `ggml-org` build) on llama.cpp, `m7i-flex.large` — free-tier eligible on this account | No | 30–90s |
| **Fallback** | Hosted Qwen (DashScope `qwen-vl-max` or OpenRouter) | No | 3–8s |

All three are wired up and swappable purely through environment variables
(`VLM_PRIMARY_BASE_URL`, `VLM_PRIMARY_MODEL`, …). Development happened
entirely against the hosted path so the quota approval was never on the
critical path for building the application itself.

## 4. Request flow

```
Browser                     EC2 t3.micro (app tier, always on)
┌──────────┐   HTTPS        ┌────────────────────────────────────────┐
│ React SPA│◄──────────────►│ Caddy (auto TLS)                        │
│ dropzone │                │   └─► FastAPI (uvicorn)                 │
│ table    │                │        1. validate + store upload       │
│ export   │                │        2. bounded-concurrency worker    │
└──────────┘                │        3. VLM adapter (primary/fallback)│──┐
                             │        4. Pydantic schema validation    │  │ OpenAI-
                             │        5. deterministic normalization   │  │ compatible
                             │        6. SQLite (jobs, leads)          │  │
                             │        7. openpyxl XLSX export          │  │
                             └────────────────────────────────────────┘  │
                                                                          ▼
                                                        EC2 g4dn.xlarge (GPU, spot)
                                                        vLLM + Qwen2.5-VL-7B-AWQ
```

1. User drops N images → `POST /api/jobs` (multipart) → `202`-style
   response with a `job_id`; the batch starts processing immediately in a
   background asyncio task, bounded by a semaphore
   (`PROCESSING_CONCURRENCY`, default 4) so a 40-card batch doesn't open 40
   simultaneous connections to the inference server.
2. Per card: validate by magic bytes (never trust the filename/Content-Type)
   → EXIF-orient → downscale to a 1280px long edge → re-encode JPEG q85 →
   base64 data URL.
3. One VLM call per card against a strict JSON-schema prompt
   (`backend/app/vlm/prompts.py`). The response is parsed defensively
   (`backend/app/vlm/parser.py` strips markdown fences, repairs trailing
   commas, coerces type slips) and validated against a Pydantic schema
   before it's trusted.
4. Deterministic post-processing (`backend/app/postprocess.py`): name
   splitting via `nameparser`, phone → E.164 via `phonenumbers`, email
   syntax validation, and warning flags for anything uncertain.
5. The row is persisted to SQLite and immediately visible — the frontend
   polls `GET /api/jobs/{id}` and rows stream into the results table as
   each card finishes, rather than the UI waiting for the whole batch.
6. The user can hand-correct any field inline before exporting (no VLM is
   100% on glare, rotation, or bilingual cards — this is the difference
   between a demo and a usable tool).
7. `GET /api/jobs/{id}/export.xlsx` streams a styled workbook built with
   `openpyxl`.

## 5. Why FastAPI + SQLite instead of a heavier stack

**Decision:** FastAPI with a single SQLite file via `aiosqlite`, no
separate database service, no task queue (Celery/Redis), no ORM.

**Why:** the whole app needs to run comfortably on a 1 GB instance and be
operable by one person. SQLite in WAL mode handles this workload (bursty,
low-concurrency, single-writer-process) without another service to
provision, secure, and pay for. Async endpoints plus an `asyncio.Semaphore`
give bounded concurrent processing without a broker. Two tables
(`jobs`, `leads`) and hand-written SQL are more legible here than an ORM
layer over them would be, and there's no multi-developer team to justify
the abstraction cost.

**Trade-off accepted:** this does not horizontally scale past one app
instance. That's fine for the assignment's scope (a lead-extraction tool
for uploaded batches, not a high-throughput SaaS) and is called out here
rather than hidden — if usage ever demanded it, the natural next step is
swapping SQLite for Postgres (the query layer is already isolated in
`backend/app/db.py`) and moving the job queue to something durable.

## 6. Why the prompt (not fine-tuning) is the extraction strategy

**Decision:** extraction quality comes entirely from prompt engineering
against a general-purpose Qwen2.5-VL checkpoint — no fine-tuning, no LoRA.

**Why:** Qwen2.5-VL already has strong OCR and layout understanding
out of the box, including for non-Latin scripts (useful for international
business cards). The prompt (`backend/app/vlm/prompts.py`) does the rest:
it specifies the exact JSON schema, gives explicit rules for ambiguous
cases (company name vs. tagline, which of several phone numbers is
primary, never inventing a value), and asks the model to self-report a
confidence score. A second, stricter "transcribe first, then extract"
prompt variant is used as a retry when the first attempt is low-confidence
or fails to parse — this alone recovers a meaningful fraction of otherwise-
failed cards without ever touching model weights.

**Why this was the right call for this project:** fine-tuning needs a
labeled training set an order of magnitude larger than what's practical to
hand-label for a submission like this, plus GPU time to train and version
control for weights. Prompting is iterable in minutes and the eval harness
(`backend/scripts/eval.py`) measures it directly — see §8.

## 7. Defensive parsing, not trust

**Decision:** the VLM's raw text output is never deserialized directly. It
passes through `extract_json_object()` (strips markdown fences, finds the
first balanced `{...}` span, ignoring braces inside string values) and a
trailing-comma repair pass, *then* Pydantic validation
(`backend/app/vlm/parser.py`).

**Why:** VLMs reliably wrap JSON in ` ```json ` fences, add a stray
sentence before or after it, or emit a trailing comma — despite explicit
instructions not to. Treating this as the normal case (not an edge case)
is what makes the pipeline reliable across three different backend
implementations with three different fine-tuning histories, rather than
just the one backend it happened to be tested against.

## 8. The eval harness — turning "seems to work" into a number

**Decision:** `backend/scripts/eval.py` runs the full extraction pipeline
against a labeled set of card images and reports per-field accuracy
(first name, last name, job title, company, location, phone, email),
matched after normalization so formatting differences don't count as
errors.

**Why:** "the VLM seems to work" is not a claim a reviewer can check.
A per-field accuracy number against a labeled set is. `scripts/generate_sample_cards.py`
produces a small synthetic set for pipeline smoke-testing (clean, flat,
printed text — intentionally easy), but the harness is meant to be pointed
at real photographed cards for a representative number; see the README for
the current result and how to reproduce it.

## 9. Image handling as a first-class stage, not an afterthought

**Decision:** every upload passes through explicit validation and
normalization (`backend/app/image_pipeline.py`) before it ever reaches the
VLM or touches disk under a trusted name:

- **Magic-byte sniffing**, not filename extension or client-supplied
  `Content-Type` — a `.jpg` that isn't actually a JPEG is rejected before
  Pillow ever opens it.
- **EXIF auto-orientation**, then EXIF is stripped — phone photos are
  very often sideways as stored, and stripping metadata also drops any
  embedded GPS/device data from the original photo (this app handles
  enough PII already without keeping more than necessary).
- **Downscaling to a 1280px long edge** bounds both VLM latency/cost and
  upload payload size, without losing the legibility of printed card text.
- **A separate 256px thumbnail** is generated for the results table so the
  UI never ships full-resolution images to the browser just to render a
  preview.

## 10. Privacy and retention

Business cards are personal data — a name, direct phone number, and email
tied to an identifiable person. This shaped several decisions rather than
being bolted on afterward:

- Uploaded images and extracted rows are deleted automatically after
  `RETENTION_MINUTES` (default 60) by a background sweeper
  (`backend/app/jobs.py::retention_sweeper_loop`).
- A card's on-disk paths are recorded **as soon as the files are written**,
  independent of whether extraction later succeeds or fails — otherwise a
  failed extraction would silently orphan an image the retention sweeper
  could never find and delete (this was caught during testing; see the git
  history for the fix and its regression test).
- The user can clear a batch immediately (`DELETE /api/jobs/{id}`) rather
  than waiting out the retention window.
- No PII is written to application logs.
- The whole app is served over HTTPS only (Caddy terminates TLS; there is
  no plaintext HTTP path in production).

## 11. What was deliberately left out of scope

- **Authentication.** The assignment describes a single-user internal
  tool; adding auth would be straightforward (FastAPI has good support for
  it) but wasn't asked for and would add setup friction to the reviewer's
  first experience with the public URL.
- **Horizontal scaling / job queue durability.** Covered in §5 — the
  right next step if this outgrew a single instance, not a gap being
  hidden.
- **Fine-tuning.** Covered in §6.
