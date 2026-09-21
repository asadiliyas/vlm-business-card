# Libraries, Frameworks, Models & External Components

Every non-trivial dependency this project uses, why it was chosen, and what
it would take to swap it out.

## Model

| Component | What it is | Why chosen |
|---|---|---|
| **Qwen2.5-VL-7B-Instruct-AWQ** | Alibaba's open-weight vision-language model, 4-bit AWQ-quantized, served on the GPU (primary) path | Required by the assignment. AWQ quantization roughly halves VRAM/RAM needs with minimal accuracy loss, fitting a single T4 GPU (16 GB). Strong OCR + layout understanding, including non-Latin scripts. Apache 2.0 licensed. |
| **Qwen2.5-VL-3B-Instruct (GGUF, Q4_K_M)** | Smaller Qwen2.5-VL checkpoint, 4-bit GGUF quantization, served on the CPU contingency path | Used when the GPU path is unavailable (see `docs/ARCHITECTURE.md` §3). Small enough to run inference on CPU in tens of seconds per card. |
| **Qwen VL (hosted)** — `qwen-vl-max` via DashScope, or via OpenRouter | Alibaba Cloud's hosted inference endpoint for the same model family | Automatic fallback backend — see `docs/ARCHITECTURE.md` §2. Keeps the public demo available even if the self-hosted instance is down. |

## Inference serving

| Component | Role | Why chosen |
|---|---|---|
| [vLLM](https://github.com/vllm-project/vllm) | OpenAI-compatible inference server for the GPU path | High-throughput GPU serving with an out-of-the-box `/v1/chat/completions` API, official Docker image, native AWQ support. |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server` | OpenAI-compatible inference server for the CPU contingency path | The reference CPU-efficient GGUF runtime; also ships an OpenAI-compatible server out of the box, so it's a drop-in alternative base URL for the same client code. |

## Backend

| Package | Role |
|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) 0.115 | Web framework — async, typed, auto-generates the OpenAPI schema at `/docs` |
| [Uvicorn](https://www.uvicorn.org/) 0.34 (`[standard]`) | ASGI server |
| [Pydantic](https://docs.pydantic.dev/) v2 | Schema validation — the `ExtractedLead` model is the actual contract the VLM's output is forced into |
| [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | Typed environment-variable configuration (`backend/app/config.py`) |
| [httpx](https://www.python-httpx.org/) | Async HTTP client used for all VLM backend calls |
| [Pillow](https://python-pillow.org/) | Image validation, EXIF handling, downscaling, re-encoding, thumbnailing |
| [aiosqlite](https://github.com/omnilib/aiosqlite) | Async SQLite driver — see `docs/ARCHITECTURE.md` §5 for why SQLite over a separate DB service |
| [phonenumbers](https://github.com/daviddrysdale/python-phonenumbers) | Google's libphonenumber port — phone → E.164 normalization |
| [email-validator](https://github.com/JoshData/python-email-validator) | Email syntax validation/normalization |
| [nameparser](https://github.com/derek73/python-nameparser) | Splits a full name into first/middle/last, handling prefixes/suffixes |
| [openpyxl](https://openpyxl.readthedocs.io/) | Builds the downloadable `.xlsx` workbook, including forcing the phone column to text format so Excel doesn't mangle a leading `+` into scientific notation |
| `python-multipart` | Required by FastAPI/Starlette for multipart form (file upload) parsing |
| pytest / pytest-asyncio | Test runner — 70 tests across parsing, normalization, image handling, the VLM adapter's fallback chain, XLSX export, and full job-lifecycle integration |

No ORM (SQL is hand-written — two tables, see `backend/app/db.py`), no task
queue (an `asyncio.Semaphore`-bounded background task is enough at this
scale), no rate-limiting library (a ~30-line in-memory sliding-window
limiter in `backend/app/rate_limit.py` — one process on one small instance
doesn't need a distributed one).

## Frontend

| Package | Role |
|---|---|
| [React](https://react.dev/) 19 + [TypeScript](https://www.typescriptlang.org/) | UI framework |
| [Vite](https://vite.dev/) 8 | Dev server + production bundler |
| [Tailwind CSS](https://tailwindcss.com/) v4 | Styling, via the official Vite plugin (CSS-first config, no separate `tailwind.config.js`) |
| [react-dropzone](https://react-dropzone.js.org/) | Drag-and-drop multi-file upload |
| [TanStack Table](https://tanstack.com/table) v8 | Headless table logic for the editable results grid |
| `clsx` | Small conditional-classname utility |

**Note on TanStack Table version:** v9 was the `latest` tag on npm at the
time this was built but ships a substantially different, sparsely-documented
API (`createCoreRowModel`/`ReactTable` instead of the well-established
`useReactTable`/`getCoreRowModel`). We deliberately pinned to the stable,
fully-documented v8 line instead of chasing the newest tag — a judgment
call favoring maintainability over novelty.

## Infrastructure

| Component | Role |
|---|---|
| Docker (multi-stage build) | Packages frontend build + backend into one image |
| Docker Compose | Orchestrates the app container + Caddy on the app instance |
| [Caddy](https://caddyserver.com/) 2 | Reverse proxy + **automatic HTTPS** (Let's Encrypt) — no manual certificate management |
| AWS EC2 | Compute for both the app tier and the inference tier |
| AWS Elastic IP | Stable public IP for the app instance |
| AWS Service Quotas / CloudWatch / Budgets | GPU vCPU quota request, billing alarm — see `docs/DEPLOY.md` Phase 0 |
| [sslip.io](https://sslip.io/) | Free wildcard DNS resolving `<name>.<ip-with-dashes>.sslip.io` straight to the Elastic IP — gives Caddy a real hostname to issue a TLS cert for with zero DNS setup or cost |
| GitHub Actions | CI — backend tests, frontend build, Docker build on every push |

## Why not alternatives

- **Postgres/MySQL over SQLite** — unnecessary operational weight for a
  single-instance, low-concurrency workload; see `docs/ARCHITECTURE.md` §5.
- **Celery/RQ + Redis over `asyncio.Semaphore`** — same reasoning; a
  broker is infrastructure this project's scale doesn't need yet.
- **Next.js over Vite + React** — no server-side rendering or routing
  requirement; a single-page app is the entire product surface.
- **Terraform/CDK over shell scripts** — the AWS footprint is two EC2
  instances, two security groups, and an Elastic IP. Plain, heavily
  commented `aws` CLI scripts (`infra/scripts/`) are more approachable for
  a reviewer to actually read than a Terraform module would be, at this
  scale. This would be worth revisiting if the infrastructure grew.
