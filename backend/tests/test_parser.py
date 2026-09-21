"""Tests for app.vlm.parser — the seam that absorbs real-world model output
noise (markdown fences, trailing commas, stray prose, wrong types)."""
from __future__ import annotations

import pytest

from app.vlm.parser import VLMParseError, extract_json_object, parse_extracted_lead


def test_parses_clean_json():
    raw = '{"first_name": "Jane", "last_name": "Doe", "job_title": "CEO", ' \
          '"company": "Acme", "location": "Austin, TX", "phone": "+15125551234", ' \
          '"email": "jane@acme.com", "additional_phones": [], "website": null, ' \
          '"raw_text": "Jane Doe", "confidence": 0.95, "warnings": []}'
    lead = parse_extracted_lead(raw)
    assert lead.first_name == "Jane"
    assert lead.company == "Acme"
    assert lead.confidence == 0.95


def test_strips_markdown_fence():
    raw = '```json\n{"first_name": "Jane", "confidence": 0.9}\n```'
    lead = parse_extracted_lead(raw)
    assert lead.first_name == "Jane"


def test_strips_leading_and_trailing_prose():
    raw = 'Here is the extracted data:\n{"first_name": "Jane", "confidence": 0.8}\nHope this helps!'
    lead = parse_extracted_lead(raw)
    assert lead.first_name == "Jane"


def test_repairs_trailing_comma():
    raw = '{"first_name": "Jane", "last_name": "Doe",}'
    lead = parse_extracted_lead(raw)
    assert lead.last_name == "Doe"


def test_raises_on_no_json():
    with pytest.raises(VLMParseError):
        parse_extracted_lead("I could not read this card clearly.")


def test_raises_on_unbalanced_braces():
    with pytest.raises(VLMParseError):
        parse_extracted_lead('{"first_name": "Jane"')


def test_coerces_string_confidence():
    raw = '{"first_name": "Jane", "confidence": "0.7"}'
    lead = parse_extracted_lead(raw)
    assert lead.confidence == 0.7


def test_coerces_0_100_scale_confidence():
    raw = '{"first_name": "Jane", "confidence": 90}'
    lead = parse_extracted_lead(raw)
    assert lead.confidence == 0.9


def test_coerces_string_additional_phones():
    raw = '{"first_name": "Jane", "additional_phones": "+1 555 000 1111", "confidence": 0.5}'
    lead = parse_extracted_lead(raw)
    assert lead.additional_phones == ["+1 555 000 1111"]


def test_empty_strings_become_null():
    raw = '{"first_name": "Jane", "email": "", "confidence": 0.5}'
    lead = parse_extracted_lead(raw)
    assert lead.email is None


def test_extract_json_object_handles_nested_braces():
    raw = 'prefix {"a": {"b": 1}, "c": [1, 2]} suffix'
    result = extract_json_object(raw)
    assert result == '{"a": {"b": 1}, "c": [1, 2]}'


def test_extract_json_object_ignores_braces_inside_strings():
    raw = '{"raw_text": "Address: {not a brace}", "first_name": "Jane"}'
    result = extract_json_object(raw)
    import json
    parsed = json.loads(result)
    assert parsed["first_name"] == "Jane"
