"""
Turns a VLM's raw text completion into a validated ExtractedLead — or raises
VLMParseError so the caller can retry. VLMs reliably wrap JSON in markdown
fences, add a stray sentence before/after it, or emit trailing commas; this
module is the seam that absorbs all of that so nothing downstream ever sees
malformed output.
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.models import ExtractedLead

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


class VLMParseError(Exception):
    """Raised when a VLM response cannot be coerced into ExtractedLead."""


def extract_json_object(text: str) -> str:
    """Pull the most likely JSON object out of a noisy completion string."""
    text = text.strip()

    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    # Fall back to the first balanced {...} span — handles a stray leading/
    # trailing sentence the model added despite instructions not to.
    start = text.find("{")
    if start == -1:
        raise VLMParseError("No JSON object found in VLM response")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise VLMParseError("Unbalanced JSON object in VLM response")


def _repair_json(raw: str) -> str:
    return _TRAILING_COMMA_RE.sub(r"\1", raw)


def parse_extracted_lead(raw_response: str) -> ExtractedLead:
    """
    Parse a VLM completion into ExtractedLead.

    Raises VLMParseError on anything unrecoverable — the caller decides
    whether to retry, not this function.
    """
    try:
        candidate = extract_json_object(raw_response)
    except VLMParseError:
        raise

    for attempt in (candidate, _repair_json(candidate)):
        try:
            data = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        try:
            return ExtractedLead.model_validate(_coerce_types(data))
        except ValidationError as exc:
            raise VLMParseError(f"Schema validation failed: {exc}") from exc

    raise VLMParseError(f"Could not parse JSON from VLM response: {raw_response[:200]!r}")


def _coerce_types(data: dict) -> dict:
    """Fix the handful of type slips models commonly make against our schema."""
    out = dict(data)

    # Some models return additional_phones / warnings as a single string.
    for key in ("additional_phones", "warnings"):
        val = out.get(key)
        if isinstance(val, str):
            out[key] = [val] if val.strip() else []
        elif val is None:
            out[key] = []

    # confidence sometimes comes back as a string ("0.9") or a 0-100 scale.
    conf = out.get("confidence")
    if isinstance(conf, str):
        try:
            conf = float(conf)
        except ValueError:
            conf = 0.5
    if isinstance(conf, (int, float)) and conf > 1:
        conf = conf / 100.0
    out["confidence"] = conf if isinstance(conf, (int, float)) else 0.5

    # Empty-string fields are more useful to us as null.
    for key in ("first_name", "last_name", "job_title", "company", "location",
                "phone", "email", "website"):
        if out.get(key) == "":
            out[key] = None

    return out
