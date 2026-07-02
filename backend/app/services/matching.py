"""Role taxonomy for title matching.

The dashboard search should behave like a job board: searching "Product Manager"
should also surface "Product Lead", "Group PM", "Head of Product", etc. — related
titles, not just literal substring matches.

We do this deterministically with a curated taxonomy of role *families* (sets of
equivalent/adjacent titles). A query is expanded to every alias in the families it
belongs to, and the API matches a job if its normalized title contains ANY alias.
Queries that map to no family fall back to strict all-tokens matching.

This is the same foundation a large job board uses under its ML layer. True
semantic matching for titles NOT in the taxonomy is the Phase-4 embeddings upgrade
(pgvector) — this taxonomy is the zero-dependency, explainable layer beneath it.

Extend by adding a set to ROLE_FAMILIES. Aliases are matched case-insensitively
after title normalization (so "PM" → "product manager" already collapses here).
"""
from __future__ import annotations

from app.scrapers.extract import normalize_title

# Each set is a family of interchangeable / closely-related titles. Keep families
# tight enough that distinct roles (e.g. Product Manager vs Product Marketing
# Manager) stay separate — the user treats those as different searches.
ROLE_FAMILIES: list[set[str]] = [
    {  # Product management — expanded broadly across seniority & specializations
        "product manager", "product management", "product manager i",
        "product manager ii", "product manager iii", "product lead",
        "lead product manager", "product owner", "product management lead",
        "associate product manager", "assistant product manager",
        "junior product manager", "senior product manager", "staff product manager",
        "principal product manager", "group product manager", "lead product owner",
        "technical product manager", "digital product manager",
        "growth product manager", "platform product manager", "data product manager",
        "ai product manager", "consumer product manager", "core product manager",
        "product management specialist", "product manager growth",
        "head of product", "head of product management", "director of product",
        "director product management", "product director", "senior director product",
        "vp product", "vp of product", "vice president product",
        "chief product officer", "cpo", "product management director",
        # Intern / entry variants
        "product manager intern", "product management intern", "product intern",
        "product manager internship", "associate product manager intern",
    },
    {  # Project management — includes program/delivery-manager adjacents
        "project manager", "project management", "associate project manager",
        "junior project manager", "senior project manager", "staff project manager",
        "principal project manager", "lead project manager", "project lead",
        "technical project manager", "it project manager", "digital project manager",
        "construction project manager", "project coordinator",
        "project management office", "pmo", "program manager", "program management",
        "senior program manager", "technical program manager", "delivery manager",
        "delivery lead", "implementation manager", "engagement manager",
        "scrum master", "agile project manager", "head of program management",
        "director of program management",
        # Intern / entry variants
        "project manager intern", "project management intern",
        "program manager intern", "program management intern",
        "project management internship",
    },
    {  # Customer success
        "customer success manager", "customer success", "customer success associate",
        "customer success specialist", "senior customer success manager",
        "associate customer success manager", "customer success lead",
        "customer success director", "director of customer success",
        "head of customer success", "vp customer success",
        "vp of customer success", "customer success operations",
        "client success manager", "client success", "customer experience manager",
        "customer success executive", "strategic customer success manager",
        "enterprise customer success manager", "technical customer success manager",
        "customer success engineer",
        # Intern / entry variants
        "customer success intern", "customer success internship",
    },
    {  # Product marketing (deliberately separate from product management)
        "product marketing manager", "product marketing", "product marketing lead",
        "associate product marketing manager", "senior product marketing manager",
        "principal product marketing manager", "group product marketing manager",
        "head of product marketing", "director of product marketing",
        "product marketing director", "vp product marketing",
        "vp of product marketing", "product marketing specialist",
        "product marketing associate", "product marketing coordinator",
        # Intern / entry variants
        "product marketing intern", "product marketing manager intern",
        "product marketing internship",
    },
    {  # Product operations
        "product operations", "product operations manager", "product ops",
    },
    {  # Engineering management (illustrates extensibility)
        "engineering manager", "engineering lead", "head of engineering",
        "director of engineering", "vp engineering", "tech lead",
    },
    {  # Data / analytics
        "data analyst", "data analysis", "business analyst", "analytics manager",
    },
    {  # Data science / ML
        "data scientist", "data science", "machine learning engineer", "ml engineer",
    },
]

# Precompute normalized families once at import.
_NORM_FAMILIES: list[set[str]] = [
    {normalize_title(alias) for alias in family} for family in ROLE_FAMILIES
]


def _family_matches_query(norm_query: str, norm_family: set[str]) -> bool:
    """A family is relevant if the query equals, contains, or is contained by any
    of its aliases (so "senior product manager" and "pm" both hit the PM family)."""
    for alias in norm_family:
        if norm_query == alias or alias in norm_query or norm_query in alias:
            return True
    return False


def expand_query(query: str) -> list[str]:
    """Return the set of normalized title phrases to OR-match for this query.

    Always includes the normalized query itself. If the query belongs to one or
    more role families, every alias in those families is included too. When only
    the query itself is returned, the caller should fall back to token matching.
    """
    norm_query = normalize_title(query)
    if not norm_query:
        return []
    phrases: set[str] = {norm_query}
    for norm_family in _NORM_FAMILIES:
        if _family_matches_query(norm_query, norm_family):
            phrases |= norm_family
    return sorted(phrases)
