"""
Deterministic cleanup applied to every VLM extraction before it's persisted:
name splitting when the model collapses to one field, phone -> E.164,
email validation, and light text normalization. None of this calls the VLM —
it's pure post-processing so it's cheap, fast, and independently testable.
"""
from __future__ import annotations

import re

import phonenumbers
from email_validator import EmailNotValidError, validate_email
from nameparser import HumanName

from app.models import ExtractedLead

# Common OCR/VLM misreads of the '@' and dot in emails, worth a light repair
# pass before we give up and flag it instead of silently dropping the email.
_EMAIL_TYPO_FIXES = [
    (re.compile(r"\s+at\s+", re.IGNORECASE), "@"),
    (re.compile(r"\s*\[at\]\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s+dot\s+", re.IGNORECASE), "."),
]


def split_name(first_name: str | None, last_name: str | None) -> tuple[str | None, str | None]:
    """
    If the VLM already split the name, trust it. If it only ever fills one of
    the two fields with what's clearly a full name (a space-separated run),
    fall back to nameparser to split it properly (handles prefixes, suffixes,
    and multi-part surnames like "van der Berg").
    """
    first = (first_name or "").strip() or None
    last = (last_name or "").strip() or None

    if first and last:
        return first, last

    full = first or last
    if not full:
        return None, None

    parsed = HumanName(full)
    new_first = parsed.first or None
    new_last = " ".join(p for p in (parsed.middle, parsed.last) if p).strip() or None

    if new_first or new_last:
        return new_first or first, new_last or last
    return first, last


def normalize_phone(raw: str | None, *, default_region: str | None = None) -> tuple[str | None, bool]:
    """
    Returns (e164_or_original, was_normalized). If parsing fails, the original
    string is preserved (a human can still read/use it) rather than dropped.
    """
    if not raw or not raw.strip():
        return None, False

    cleaned = raw.strip()
    regions_to_try = [default_region, None, "US"]
    for region in regions_to_try:
        try:
            parsed = phonenumbers.parse(cleaned, region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), True

    return cleaned, False


def normalize_email(raw: str | None) -> tuple[str | None, list[str]]:
    """Returns (cleaned_email_or_original, warnings)."""
    if not raw or not raw.strip():
        return None, []

    candidate = raw.strip().lower()
    for pattern, replacement in _EMAIL_TYPO_FIXES:
        candidate = pattern.sub(replacement, candidate)
    candidate = candidate.replace(" ", "")

    try:
        result = validate_email(candidate, check_deliverability=False)
        return result.normalized, []
    except EmailNotValidError:
        return candidate, ["email_failed_validation"]


def guess_region_from_location(location: str | None) -> str | None:
    """Very small country-name -> ISO region map, just enough to bias phone
    parsing toward the right country when the model didn't include a + code."""
    if not location:
        return None
    loc = location.lower()
    mapping = {
        "united states": "US", "usa": "US", "u.s.a": "US",
        "united kingdom": "GB", "uk": "GB",
        "canada": "CA", "australia": "AU", "india": "IN",
        "pakistan": "PK", "uae": "AE", "united arab emirates": "AE",
        "germany": "DE", "france": "FR", "china": "CN", "japan": "JP",
        "singapore": "SG", "saudi arabia": "SA",
    }
    for name, code in mapping.items():
        if name in loc:
            return code
    return None


def postprocess_lead(extracted: ExtractedLead) -> ExtractedLead:
    """Apply all normalization steps and return a new, cleaned ExtractedLead."""
    warnings = list(extracted.warnings)

    first, last = split_name(extracted.first_name, extracted.last_name)

    region = guess_region_from_location(extracted.location)
    phone, phone_ok = normalize_phone(extracted.phone, default_region=region)
    if extracted.phone and not phone_ok:
        warnings.append("phone_not_normalized")

    normalized_additional = []
    for p in extracted.additional_phones:
        np, _ = normalize_phone(p, default_region=region)
        if np:
            normalized_additional.append(np)

    email, email_warnings = normalize_email(extracted.email)
    warnings.extend(email_warnings)

    company = (extracted.company or "").strip() or None
    location = (extracted.location or "").strip() or None
    job_title = (extracted.job_title or "").strip() or None
    website = (extracted.website or "").strip() or None

    if not first and not last:
        warnings.append("no_name_found")
    if not email:
        warnings.append("no_email_found")
    if not phone:
        warnings.append("no_phone_found")

    return extracted.model_copy(
        update={
            "first_name": first,
            "last_name": last,
            "job_title": job_title,
            "company": company,
            "location": location,
            "phone": phone,
            "email": email,
            "additional_phones": normalized_additional,
            "website": website,
            "warnings": sorted(set(warnings)),
        }
    )


def find_duplicate_groups(leads: list[dict]) -> dict[str, list[str]]:
    """
    Groups lead ids that share a normalized email or phone. Used to flag
    (never auto-merge) probable duplicates within one batch, e.g. a card
    photographed twice or a double-sided card processed as two files.
    Returns {lead_id: [other_lead_ids_it_duplicates]}.
    """
    by_email: dict[str, list[str]] = {}
    by_phone: dict[str, list[str]] = {}
    for lead in leads:
        if lead.get("email"):
            by_email.setdefault(lead["email"], []).append(lead["id"])
        if lead.get("phone"):
            by_phone.setdefault(lead["phone"], []).append(lead["id"])

    result: dict[str, list[str]] = {}
    for group in list(by_email.values()) + list(by_phone.values()):
        if len(group) < 2:
            continue
        for lead_id in group:
            others = [g for g in group if g != lead_id]
            result.setdefault(lead_id, [])
            for o in others:
                if o not in result[lead_id]:
                    result[lead_id].append(o)
    return result
