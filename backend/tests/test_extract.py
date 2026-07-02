"""Unit tests for the deterministic extraction/normalization functions."""
from app.models import LocationType
from app.scrapers import extract


def test_normalize_title_expands_abbreviations():
    assert extract.normalize_title("Sr. PM") == "senior product manager"
    assert extract.normalize_title("Associate Product Manager (Remote)") == (
        "associate product manager"
    )


def test_classify_location():
    assert extract.classify_location("Remote (US)") == LocationType.remote
    assert extract.classify_location("Hybrid - New York") == LocationType.hybrid
    assert extract.classify_location("San Francisco, CA") == LocationType.onsite
    assert extract.classify_location(None) == LocationType.unknown


def test_extract_experience_range():
    assert extract.extract_experience("We need 2-4 years of experience") == (2, 4)
    assert extract.extract_experience("Minimum of 5 years required") == (5, None)
    assert extract.extract_experience("3+ years in product") == (3, None)
    assert extract.extract_experience("No numbers here") == (None, None)


def test_fingerprint_stable_across_repost_location_variants():
    # Same job, aggregator repost with a slightly different location string →
    # same fingerprint so dedup treats them as one.
    a = extract.content_fingerprint("Stripe", "Sr. PM", "Remote, US")
    b = extract.content_fingerprint("stripe", "Senior Product Manager", "Remote")
    assert a == b


def test_parse_relative_posted():
    from datetime import datetime, timezone
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert extract.parse_relative_posted("Posted Today", now=ref) == ref
    assert extract.parse_relative_posted("Posted Yesterday", now=ref).day == 30
    assert extract.parse_relative_posted("Posted 3 Days Ago", now=ref).day == 28
    assert extract.parse_relative_posted("Posted 30+ Days Ago", now=ref).day == 1
    assert extract.parse_relative_posted(None) is None
    assert extract.parse_relative_posted("no date here") is None


def test_parse_salary_summary():
    lo, hi, cur = extract.parse_salary_summary("$191K – $291K")
    assert (lo, hi, cur) == (191000.0, 291000.0, "USD")
    assert extract.parse_salary_summary("competitive") == (None, None, None)


def test_content_hash_changes_on_description_edit():
    h1 = extract.content_hash(
        title="PM", location_raw="Remote", description="old",
        salary_min=None, salary_max=None,
    )
    h2 = extract.content_hash(
        title="PM", location_raw="Remote", description="new",
        salary_min=None, salary_max=None,
    )
    assert h1 != h2
