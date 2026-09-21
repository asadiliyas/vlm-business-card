from __future__ import annotations

from app.models import ExtractedLead
from app.postprocess import (
    find_duplicate_groups,
    guess_region_from_location,
    normalize_email,
    normalize_phone,
    postprocess_lead,
    split_name,
)


class TestSplitName:
    def test_already_split_is_kept(self):
        assert split_name("Jane", "Doe") == ("Jane", "Doe")

    def test_splits_full_name_in_first_field(self):
        first, last = split_name("Dr. Jane Smith-Okoye", None)
        assert first == "Jane"
        assert "Smith-Okoye" in (last or "")

    def test_handles_both_none(self):
        assert split_name(None, None) == (None, None)

    def test_handles_empty_strings(self):
        assert split_name("", "") == (None, None)


class TestNormalizePhone:
    def test_e164_with_country_code(self):
        result, ok = normalize_phone("+1 (512) 555-1234")
        assert ok is True
        assert result == "+15125551234"

    def test_none_input(self):
        assert normalize_phone(None) == (None, False)

    def test_unparseable_number_preserved(self):
        result, ok = normalize_phone("call me maybe")
        assert ok is False
        assert result == "call me maybe"

    def test_uses_region_hint(self):
        result, ok = normalize_phone("020 7946 0958", default_region="GB")
        assert ok is True
        assert result.startswith("+44")


class TestNormalizeEmail:
    def test_valid_email_lowercased(self):
        result, warnings = normalize_email("Jane.Doe@ACME.com")
        assert result == "jane.doe@acme.com"
        assert warnings == []

    def test_none_input(self):
        assert normalize_email(None) == (None, [])

    def test_fixes_spaces_around_at(self):
        result, _ = normalize_email("jane @ acme.com")
        assert result == "jane@acme.com"

    def test_fixes_at_word(self):
        result, _ = normalize_email("jane at acme dot com")
        assert result == "jane@acme.com"

    def test_invalid_email_flagged_not_dropped(self):
        result, warnings = normalize_email("not-an-email")
        assert result == "not-an-email"
        assert "email_failed_validation" in warnings


class TestGuessRegion:
    def test_finds_country_in_location(self):
        assert guess_region_from_location("London, United Kingdom") == "GB"

    def test_none_when_no_match(self):
        assert guess_region_from_location("Somewhere, Nowhere") is None

    def test_none_input(self):
        assert guess_region_from_location(None) is None


class TestPostprocessLead:
    def test_full_pipeline(self):
        raw = ExtractedLead(
            first_name="Jane",
            last_name="Doe",
            job_title="  CEO  ",
            company="  Acme Corp  ",
            location="Austin, Texas, United States",
            phone="(512) 555-1234",
            email="JANE @ ACME.COM",
            confidence=0.9,
        )
        cleaned = postprocess_lead(raw)
        assert cleaned.job_title == "CEO"
        assert cleaned.company == "Acme Corp"
        assert cleaned.phone == "+15125551234"
        assert cleaned.email == "jane@acme.com"

    def test_flags_missing_fields(self):
        raw = ExtractedLead(company="Acme Corp", confidence=0.5)
        cleaned = postprocess_lead(raw)
        assert "no_name_found" in cleaned.warnings
        assert "no_email_found" in cleaned.warnings
        assert "no_phone_found" in cleaned.warnings

    def test_company_only_card_no_warnings_for_name_if_intentional(self):
        # Company-only cards are valid; we still flag no_name_found so a
        # reviewer can see it was empty rather than silently dropped, but it
        # must not raise or corrupt other fields.
        raw = ExtractedLead(company="Acme Corp", email="info@acme.com", confidence=0.7)
        cleaned = postprocess_lead(raw)
        assert cleaned.company == "Acme Corp"
        assert cleaned.email == "info@acme.com"


class TestDuplicateGroups:
    def test_finds_shared_email(self):
        leads = [
            {"id": "a", "email": "x@y.com", "phone": None},
            {"id": "b", "email": "x@y.com", "phone": None},
            {"id": "c", "email": "other@y.com", "phone": None},
        ]
        groups = find_duplicate_groups(leads)
        assert groups["a"] == ["b"]
        assert groups["b"] == ["a"]
        assert "c" not in groups

    def test_no_duplicates(self):
        leads = [{"id": "a", "email": "x@y.com", "phone": None}]
        assert find_duplicate_groups(leads) == {}
