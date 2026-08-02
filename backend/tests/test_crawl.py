"""Crawl orchestration: which companies get swept, and concurrently."""
import asyncio

import httpx
import pytest
from sqlalchemy import select

from app.models import ATSProvider, Company, CrawlRun
from app.scrapers.base import CompanyRef, NormalizedJob
from app.services import crawl as crawl_service


class _StubScraper:
    """Records what it was asked to fetch and returns one posting."""

    def __init__(self, seen: list[str]):
        self._seen = seen

    async def fetch_jobs(self, company: CompanyRef) -> list[NormalizedJob]:
        self._seen.append(company.ats_identifier)
        await asyncio.sleep(0)  # yield, so concurrent tasks interleave
        return [
            NormalizedJob(
                external_id=f"{company.ats_identifier}-1",
                title="Software Engineer",
                apply_url="https://example.com/1",
                company_name=company.name,
                location_raw="San Francisco, CA",
            )
        ]


def _company(name: str, provider: ATSProvider) -> Company:
    slug = f"{name.lower()}-{provider.value}"
    return Company(
        name=name, slug=slug, ats_provider=provider, ats_identifier=slug, active=True
    )


@pytest.fixture
def stub_scraper(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        crawl_service, "get_scraper", lambda provider: _StubScraper(seen)
    )
    return seen


async def test_crawl_skips_providers_without_a_scraper(
    session, session_factory, stub_scraper
):
    """Aggregator companies must not be dispatched to the scraper registry.

    services/aggregate.py creates a Company per employer in a feed, with a
    provider that has no scraper on purpose. Sweeping them costs a failed
    CrawlRun and two round trips each, and in production that was 1,243 of
    1,409 companies on every crawl.
    """
    session.add_all(
        [
            _company("Stripe", ATSProvider.greenhouse),
            _company("Ramp", ATSProvider.ashby),
            _company("Feed Employer", ATSProvider.adzuna),
            _company("Muse Employer", ATSProvider.themuse),
            _company("Jobicy Employer", ATSProvider.jobicy),
        ]
    )
    await session.commit()

    runs = await crawl_service.crawl_all(session, session_factory=session_factory)

    assert sorted(stub_scraper) == ["ramp-ashby", "stripe-greenhouse"]
    assert {r.provider for r in runs} == {ATSProvider.greenhouse, ATSProvider.ashby}
    assert all(r.ok for r in runs)

    # No CrawlRun row should exist for a provider we cannot crawl.
    providers = (await session.execute(select(CrawlRun.provider))).scalars().all()
    assert ATSProvider.adzuna not in providers
    assert len(providers) == 2


async def test_crawl_skips_inactive_companies(session, session_factory, stub_scraper):
    active = _company("Stripe", ATSProvider.greenhouse)
    inactive = _company("Dormant", ATSProvider.lever)
    inactive.active = False
    session.add_all([active, inactive])
    await session.commit()

    await crawl_service.crawl_all(session, session_factory=session_factory)

    assert stub_scraper == ["stripe-greenhouse"]


async def test_crawl_is_concurrent_and_isolates_failures(
    session, session_factory, monkeypatch
):
    """One company blowing up must not take the sweep down with it."""
    monkeypatch.setattr(crawl_service.settings, "crawl_concurrency", 4)

    class _Flaky:
        async def fetch_jobs(self, company: CompanyRef):
            if company.name == "Broken":
                raise RuntimeError("board returned 500")
            return []

    monkeypatch.setattr(crawl_service, "get_scraper", lambda provider: _Flaky())

    session.add_all(
        [
            _company("Stripe", ATSProvider.greenhouse),
            _company("Broken", ATSProvider.lever),
            _company("Ramp", ATSProvider.ashby),
        ]
    )
    await session.commit()

    runs = await crawl_service.crawl_all(session, session_factory=session_factory)

    assert len(runs) == 3
    failed = [r for r in runs if not r.ok]
    assert len(failed) == 1
    assert "board returned 500" in failed[0].error


class _Gone:
    """A board that answers 404 — the company moved off this ATS."""

    def __init__(self, status: int = 404):
        self._status = status

    async def fetch_jobs(self, company: CompanyRef):
        request = httpx.Request("GET", "https://boards-api.greenhouse.io/v1/boards/x")
        response = httpx.Response(self._status, request=request)
        raise httpx.HTTPStatusError("gone", request=request, response=response)


async def test_dead_board_is_deactivated_after_repeated_404s(
    session, session_factory, monkeypatch
):
    monkeypatch.setattr(crawl_service, "get_scraper", lambda provider: _Gone())
    company = _company("Fal", ATSProvider.greenhouse)
    session.add(company)
    await session.commit()

    for expected in range(1, crawl_service.DEAD_BOARD_THRESHOLD + 1):
        await crawl_service.crawl_all(session, session_factory=session_factory)
        await session.refresh(company)
        assert company.consecutive_missing == expected

    assert company.active is False

    # Deactivated companies drop out of the sweep entirely.
    runs = await crawl_service.crawl_all(session, session_factory=session_factory)
    assert runs == []


async def test_transient_errors_never_retire_a_board(
    session, session_factory, monkeypatch
):
    """A 500 or a timeout is an ATS having a bad day, not a dead board."""

    class _Flaky:
        async def fetch_jobs(self, company: CompanyRef):
            raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(crawl_service, "get_scraper", lambda provider: _Flaky())
    company = _company("Stripe", ATSProvider.greenhouse)
    session.add(company)
    await session.commit()

    for _ in range(crawl_service.DEAD_BOARD_THRESHOLD + 2):
        await crawl_service.crawl_all(session, session_factory=session_factory)

    await session.refresh(company)
    assert company.consecutive_missing == 0
    assert company.active is True


async def test_a_recovered_board_resets_its_counter(
    session, session_factory, monkeypatch
):
    company = _company("Ramp", ATSProvider.ashby)
    session.add(company)
    await session.commit()

    monkeypatch.setattr(crawl_service, "get_scraper", lambda provider: _Gone())
    for _ in range(3):
        await crawl_service.crawl_all(session, session_factory=session_factory)
    await session.refresh(company)
    assert company.consecutive_missing == 3
    assert company.active is True  # still under the threshold

    monkeypatch.setattr(crawl_service, "get_scraper", lambda provider: _StubScraper([]))
    await crawl_service.crawl_all(session, session_factory=session_factory)
    await session.refresh(company)
    assert company.consecutive_missing == 0
