"""
Centralized application settings, loaded from environment variables / .env.

Every tunable that differs between local dev, the CPU contingency deploy, and
the GPU primary deploy lives here — nothing else in the codebase should read
os.environ directly. See .env.example for documentation of each field.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "VLM Business Card Lead Extractor"
    environment: str = "development"  # development | production
    data_dir: Path = Path("./data")
    retention_minutes: int = 60  # how long uploaded images/leads are kept before sweeping

    # --- Primary VLM backend (self-hosted Qwen2.5-VL, OpenAI-compatible) ---
    vlm_primary_base_url: str = "http://localhost:8001/v1"
    vlm_primary_model: str = "Qwen2.5-VL-7B-Instruct-AWQ"
    vlm_primary_api_key: str = "not-needed"
    vlm_primary_enabled: bool = True

    # --- Fallback VLM backend (hosted Qwen, e.g. DashScope / OpenRouter) ---
    vlm_fallback_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    vlm_fallback_model: str = "qwen-vl-max"
    vlm_fallback_api_key: str = ""
    vlm_fallback_enabled: bool = True

    # --- VLM call behavior ---
    # 240s (not the more obvious 30-60s) because concurrent CPU-backed
    # inference genuinely needs this headroom: under PROCESSING_CONCURRENCY
    # requests contending for the same box, each individual call takes far
    # longer than its solo latency. Measured directly during deployment
    # testing: a single card under 2-way concurrency on a 2-vCPU box took
    # 144s end to end (~2.85 tokens/sec generation) — a first attempt at
    # 60s, then 120s, both still timed every card out before either the
    # primary retry or the fallback's own rate limit had a chance to
    # succeed. A fast GPU backend finishes in seconds regardless, so
    # raising this costs nothing there.
    vlm_timeout_seconds: float = 240.0
    vlm_max_retries: int = 2
    vlm_temperature: float = 0.0
    vlm_confidence_retry_threshold: float = 0.55

    # --- Upload / batch limits ---
    max_files_per_job: int = 40
    max_file_mb: float = 10.0
    allowed_mime_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp", "image/heic")
    # 2 (not 4) because this is safe on both deployment paths: a 2-vCPU CPU
    # inference box (the free-tier contingency, see docs/ARCHITECTURE.md
    # §1) genuinely can't usefully serve 4 concurrent vision calls — real
    # testing showed all 4 timing out under that load. A GPU backend has
    # headroom to raise this (4+) once confirmed healthy; 2 is the
    # conservative default that works out of the box either way.
    processing_concurrency: int = 2
    image_long_edge_px: int = 1280
    thumbnail_px: int = 256

    # --- Rate limiting ---
    rate_limit_per_minute: int = 20

    # --- CORS (only needed when frontend is served from a different origin, e.g. local dev) ---
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        (v / "uploads").mkdir(exist_ok=True)
        (v / "thumbnails").mkdir(exist_ok=True)
        return v

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def thumbnails_dir(self) -> Path:
        return self.data_dir / "thumbnails"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
