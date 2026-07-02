"""Tests for the role-taxonomy query expansion."""
from app.scrapers.extract import normalize_title
from app.services.matching import expand_query


def _title_matches_query(title: str, query: str) -> bool:
    """Mirror the API's SQL: a job matches if its normalized title contains any
    expanded phrase as a substring (ILIKE '%phrase%' on title_normalized)."""
    norm_title = normalize_title(title)
    phrases = expand_query(query)
    if len(phrases) > 1:  # taxonomy path (OR over phrases)
        return any(p in norm_title for p in phrases)
    return all(tok in norm_title for tok in normalize_title(query).split())


def test_product_manager_expands_to_related_titles():
    phrases = expand_query("Product Manager")
    # The PM family aliases are pulled in so lead/owner/head-of variants match.
    assert "product lead" in phrases
    assert "product owner" in phrases
    assert "head of product" in phrases
    assert "group product manager" in phrases
    # But product marketing is a separate family and must NOT be included.
    assert "product marketing manager" not in phrases


def test_pm_abbreviation_maps_to_product_family():
    # "PM" normalizes to "product manager", so it hits the same family.
    phrases = expand_query("PM")
    assert "product lead" in phrases


def test_seniority_prefix_still_expands():
    phrases = expand_query("Senior Product Manager")
    assert "product lead" in phrases


def test_product_marketing_stays_separate():
    phrases = expand_query("Product Marketing Manager")
    assert "product marketing lead" in phrases
    # Should not drag in the general product-management family.
    assert "product owner" not in phrases


def test_project_manager_family():
    phrases = expand_query("Project Manager")
    assert "program manager" in phrases
    assert "technical project manager" in phrases
    assert "delivery manager" in phrases
    # Must not collapse into the product-manager family.
    assert "product manager" not in phrases


def test_customer_success_family():
    phrases = expand_query("Customer Success Manager")
    assert "customer success" in phrases
    assert "client success manager" in phrases
    assert "customer success director" in phrases
    assert "product manager" not in phrases


def test_product_and_project_stay_distinct():
    assert "project manager" not in expand_query("Product Manager")
    assert "product owner" not in expand_query("Project Manager")


def test_product_marketing_family_and_intern():
    phrases = expand_query("Product Marketing Manager")
    assert "product marketing intern" in phrases
    assert "senior product marketing manager" in phrases
    # Still separate from product management.
    assert "product owner" not in phrases


def test_intern_titles_match_their_role_search():
    # Interns are NOT filtered out — a PM/PMM/Project intern title matches the
    # corresponding role search (proves it via the same substring logic as SQL).
    assert _title_matches_query("Product Manager Intern", "product manager")
    assert _title_matches_query("Product Management Intern - Summer 2026",
                                "product manager")
    assert _title_matches_query("Product Marketing Intern", "product marketing manager")
    assert _title_matches_query("Project Management Intern", "project manager")
    assert _title_matches_query("Customer Success Intern", "customer success manager")


def test_program_manager_matches_project_search():
    # Confirms program-manager titles are surfaced by a "project manager" search.
    assert _title_matches_query("Technical Program Manager", "project manager")


def test_unknown_query_returns_only_itself():
    # No family → caller falls back to strict token matching.
    phrases = expand_query("growth hacker")
    assert phrases == ["growth hacker"]
