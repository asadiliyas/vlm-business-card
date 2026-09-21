"""
Async client for OpenAI-compatible chat-completions VLM endpoints, with a
primary → fallback chain. This is the single seam that makes the "self-hosted
Qwen on EC2, hosted Qwen as fallback" architecture possible: vLLM, llama.cpp's
llama-server, DashScope, and OpenRouter all speak this same protocol, so this
one client drives all of them with only base_url/model/api_key changing.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import httpx

from app.config import Settings
from app.models import ExtractedLead
from app.vlm.parser import VLMParseError, parse_extracted_lead
from app.vlm.prompts import RETRY_SYSTEM_SUFFIX, SYSTEM_PROMPT, USER_PROMPT

logger = logging.getLogger("app.vlm")


class BackendName(StrEnum):
    PRIMARY = "primary"
    FALLBACK = "fallback"


class VLMError(Exception):
    """Raised when a call could not produce a usable ExtractedLead on any backend."""


@dataclass(frozen=True)
class BackendConfig:
    name: BackendName
    base_url: str
    model: str
    api_key: str
    enabled: bool


@dataclass(frozen=True)
class ExtractionResult:
    lead: ExtractedLead
    backend_used: BackendName
    attempts: int


class SupportsChat(Protocol):
    async def chat(self, *, backend: BackendConfig, system: str, image_data_url: str,
                    temperature: float, timeout: float) -> str: ...


class HttpChatTransport:
    """Real network transport — a thin wrapper over httpx against /chat/completions."""

    async def chat(self, *, backend: BackendConfig, system: str, image_data_url: str,
                    temperature: float, timeout: float) -> str:
        headers = {"Content-Type": "application/json"}
        if backend.api_key and backend.api_key != "not-needed":
            headers["Authorization"] = f"Bearer {backend.api_key}"

        payload = {
            "model": backend.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{backend.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise VLMError(f"Unexpected response shape from {backend.name}: {data!r}") from exc


def image_bytes_to_data_url(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


class VLMClient:
    """
    Drives extraction for one image: tries the primary backend (with one
    stricter retry on parse failure / low confidence), and on any failure —
    connection error, timeout, HTTP error, or repeated parse failure — falls
    over to the fallback backend so a stopped GPU instance never breaks the
    app for the end user.
    """

    def __init__(self, settings: Settings, transport: SupportsChat | None = None):
        self._settings = settings
        self._transport = transport or HttpChatTransport()
        self._backends: list[BackendConfig] = [
            BackendConfig(
                BackendName.PRIMARY,
                settings.vlm_primary_base_url,
                settings.vlm_primary_model,
                settings.vlm_primary_api_key,
                settings.vlm_primary_enabled,
            ),
            BackendConfig(
                BackendName.FALLBACK,
                settings.vlm_fallback_base_url,
                settings.vlm_fallback_model,
                settings.vlm_fallback_api_key,
                settings.vlm_fallback_enabled,
            ),
        ]

    async def extract(self, image_bytes: bytes, *, mime_type: str = "image/jpeg") -> ExtractionResult:
        image_url = image_bytes_to_data_url(image_bytes, mime_type)
        last_error: Exception | None = None

        for backend in self._backends:
            if not backend.enabled:
                continue
            try:
                return await self._extract_with_backend(backend, image_url)
            except Exception as exc:  # noqa: BLE001 — deliberately broad: any failure falls over
                logger.warning("VLM backend %s failed: %s", backend.name, exc)
                last_error = exc
                continue

        raise VLMError(f"All VLM backends failed; last error: {last_error}")

    async def _extract_with_backend(self, backend: BackendConfig, image_url: str) -> ExtractionResult:
        attempt = 0
        system = SYSTEM_PROMPT
        raw_response = ""

        for attempt in range(1, self._settings.vlm_max_retries + 2):  # first try + N retries
            raw_response = await self._call_with_backoff(backend, system, image_url)
            try:
                lead = parse_extracted_lead(raw_response)
            except VLMParseError as exc:
                logger.info("Parse failed on %s attempt %d: %s", backend.name, attempt, exc)
                system = SYSTEM_PROMPT + RETRY_SYSTEM_SUFFIX
                continue

            if lead.confidence < self._settings.vlm_confidence_retry_threshold and attempt == 1:
                system = SYSTEM_PROMPT + RETRY_SYSTEM_SUFFIX
                retry_response = await self._call_with_backoff(backend, system, image_url)
                try:
                    retry_lead = parse_extracted_lead(retry_response)
                    if retry_lead.confidence >= lead.confidence:
                        lead = retry_lead
                        attempt += 1
                except VLMParseError:
                    pass  # keep the first (parseable) result

            return ExtractionResult(lead=lead, backend_used=backend.name, attempts=attempt)

        raise VLMError(f"{backend.name} produced unparseable output after {attempt} attempts: "
                        f"{raw_response[:200]!r}")

    async def _call_with_backoff(self, backend: BackendConfig, system: str, image_url: str) -> str:
        delay = 1.0
        last_exc: Exception | None = None
        for i in range(self._settings.vlm_max_retries + 1):
            try:
                return await self._transport.chat(
                    backend=backend,
                    system=system,
                    image_data_url=image_url,
                    temperature=self._settings.vlm_temperature,
                    timeout=self._settings.vlm_timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if i < self._settings.vlm_max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
        assert last_exc is not None
        raise last_exc


async def check_backend_health(base_url: str, timeout: float = 5.0) -> bool:
    """Best-effort health probe used by /api/health — hits /models, ignores auth."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/models")
            return resp.status_code < 500
    except Exception:  # noqa: BLE001
        return False
