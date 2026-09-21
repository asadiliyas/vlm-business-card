"""
Tests the primary -> fallback chain and retry behavior using a fake transport
(no real network calls) — this is what lets the whole extraction pipeline be
tested and trusted before a real Qwen deployment exists.
"""
from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.vlm.client import BackendConfig, VLMClient, VLMError

GOOD_JSON = '{"first_name": "Jane", "last_name": "Doe", "confidence": 0.9, "raw_text": "Jane Doe"}'
LOW_CONF_JSON = '{"first_name": "Blurry", "confidence": 0.2, "raw_text": "?"}'
HIGH_CONF_JSON = '{"first_name": "Clear", "confidence": 0.95, "raw_text": "Clear Name"}'


def make_settings(**overrides) -> Settings:
    defaults = dict(
        vlm_primary_base_url="http://primary.test/v1",
        vlm_primary_model="test-model",
        vlm_primary_api_key="key",
        vlm_primary_enabled=True,
        vlm_fallback_base_url="http://fallback.test/v1",
        vlm_fallback_model="fallback-model",
        vlm_fallback_api_key="key2",
        vlm_fallback_enabled=True,
        vlm_max_retries=1,
        vlm_timeout_seconds=1.0,
        vlm_confidence_retry_threshold=0.55,
    )
    defaults.update(overrides)
    return Settings(**defaults)


class ScriptedTransport:
    """Replays a scripted sequence of responses/exceptions per backend name,
    in call order, so tests can assert exact fallback/retry behavior."""

    def __init__(self, script: dict[str, list]):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[str] = []

    async def chat(self, *, backend: BackendConfig, system: str, image_data_url: str,
                    temperature: float, timeout: float) -> str:
        self.calls.append(backend.name)
        queue = self.script.get(backend.name, [])
        if not queue:
            raise AssertionError(f"No scripted response left for backend {backend.name}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_primary_success_no_fallback_needed():
    transport = ScriptedTransport({"primary": [GOOD_JSON]})
    client = VLMClient(make_settings(), transport=transport)
    result = await client.extract(b"fake-image-bytes")
    assert result.lead.first_name == "Jane"
    assert result.backend_used == "primary"
    assert transport.calls == ["primary"]


@pytest.mark.asyncio
async def test_falls_back_when_primary_connection_fails():
    transport = ScriptedTransport({
        "primary": [httpx.ConnectError("connection refused")],
        "fallback": [GOOD_JSON],
    })
    client = VLMClient(make_settings(vlm_max_retries=0), transport=transport)
    result = await client.extract(b"fake-image-bytes")
    assert result.backend_used == "fallback"
    assert result.lead.first_name == "Jane"


@pytest.mark.asyncio
async def test_falls_back_when_primary_returns_unparseable_output():
    transport = ScriptedTransport({
        "primary": ["not json at all", "still not json"],
        "fallback": [GOOD_JSON],
    })
    client = VLMClient(make_settings(vlm_max_retries=0), transport=transport)
    result = await client.extract(b"fake-image-bytes")
    assert result.backend_used == "fallback"


@pytest.mark.asyncio
async def test_raises_when_all_backends_fail():
    transport = ScriptedTransport({
        "primary": [httpx.ConnectError("refused")],
        "fallback": [httpx.ConnectError("refused")],
    })
    client = VLMClient(make_settings(vlm_max_retries=0), transport=transport)
    with pytest.raises(VLMError):
        await client.extract(b"fake-image-bytes")


@pytest.mark.asyncio
async def test_low_confidence_triggers_one_retry_on_same_backend():
    transport = ScriptedTransport({"primary": [LOW_CONF_JSON, HIGH_CONF_JSON]})
    client = VLMClient(make_settings(), transport=transport)
    result = await client.extract(b"fake-image-bytes")
    assert result.lead.first_name == "Clear"
    assert result.backend_used == "primary"
    assert transport.calls == ["primary", "primary"]


@pytest.mark.asyncio
async def test_low_confidence_retry_keeps_first_if_retry_is_worse():
    # Retry returns unparseable garbage — should keep the first, parseable result.
    transport = ScriptedTransport({"primary": [LOW_CONF_JSON, "garbage, not json"]})
    client = VLMClient(make_settings(), transport=transport)
    result = await client.extract(b"fake-image-bytes")
    assert result.lead.first_name == "Blurry"


@pytest.mark.asyncio
async def test_disabled_backend_is_skipped():
    transport = ScriptedTransport({"fallback": [GOOD_JSON]})
    client = VLMClient(make_settings(vlm_primary_enabled=False), transport=transport)
    result = await client.extract(b"fake-image-bytes")
    assert result.backend_used == "fallback"
    assert "primary" not in transport.calls
