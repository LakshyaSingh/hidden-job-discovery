"""The scraper contract every ATS provider implements.

Adding a provider = one module that subclasses BaseScraper and calls @register.
Scrapers know nothing about the database; they only emit NormalizedJob objects.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.models import ATSProvider, LocationType


@dataclass
class CompanyRef:
    """Minimal company info a scraper needs to fetch jobs."""

    name: str
    ats_identifier: str  # e.g. Greenhouse board token, Lever site slug
    careers_url: str | None = None


@dataclass
class NormalizedJob:
    """Provider-agnostic job record. This is the ONLY contract ingest depends on.

    Scrapers fill what they can; extractors/ingest enrich the rest. Fields left
    as None mean "the source did not provide this", never "zero".
    """

    external_id: str
    title: str
    apply_url: str
    company_name: str

    location_raw: str | None = None
    location_type: LocationType = LocationType.unknown
    # True/False when the scraper knows the country; None → let ingest infer it.
    is_us: bool | None = None
    original_posted_at: datetime | None = None  # authoritative publish date if known
    employment_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    description: str | None = None
    skills: list[str] = field(default_factory=list)
    min_experience: int | None = None
    max_experience: int | None = None


class BaseScraper(ABC):
    provider: ClassVar[ATSProvider]

    @abstractmethod
    async def fetch_jobs(self, company: CompanyRef) -> list[NormalizedJob]:
        """Return all current postings for the company. May be a listing-only
        pass; expensive detail fetching can be deferred to fetch_detail."""

    async def fetch_detail(
        self, company: CompanyRef, external_id: str
    ) -> NormalizedJob | None:
        """Optional: fetch one posting's full detail. Default: not supported."""
        return None


# --- Provider registry -------------------------------------------------------

_REGISTRY: dict[ATSProvider, type[BaseScraper]] = {}


def register(cls: type[BaseScraper]) -> type[BaseScraper]:
    """Class decorator: make a scraper discoverable by its provider enum."""
    _REGISTRY[cls.provider] = cls
    return cls


def get_scraper(provider: ATSProvider) -> BaseScraper:
    if provider not in _REGISTRY:
        raise KeyError(f"No scraper registered for provider {provider!r}")
    return _REGISTRY[provider]()


def supported_providers() -> list[ATSProvider]:
    return sorted(_REGISTRY.keys(), key=lambda p: p.value)
