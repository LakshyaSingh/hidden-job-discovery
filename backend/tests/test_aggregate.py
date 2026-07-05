"""Tests for aggregator ingestion (network mocked)."""
import pytest
from sqlalchemy import select

from app.models import ATSProvider, Company, Job
from app.scrapers.base import NormalizedJob
from app.services.aggregate import _slugify, ingest_source


def test_slugify():
    assert _slugify("Modern Treasury") == "modern-treasury"
    assert _slugify("AT&T, Inc.") == "at-t-inc"


def test_remotive_us_eligibility():
    from app.aggregators.remotive import _us_eligible
    assert _us_eligible("USA") is True
    assert _us_eligible("USA, Canada, USA timezones") is True
    assert _us_eligible("North America") is True
    assert _us_eligible("Worldwide") is True
    assert _us_eligible("Canada") is False
    assert _us_eligible("Germany") is False
    assert _us_eligible("LATAM, Europe") is False
    assert _us_eligible(None) is False


def test_jobicy_level_mapping():
    from app.aggregators.jobicy import _level_exp
    assert _level_exp("Senior") == (5, None)
    assert _level_exp("Entry-Level") == (0, 2)
    assert _level_exp("Executive") == (10, None)
    assert _level_exp(None) == (None, None)


@pytest.mark.asyncio
async def test_adzuna_skips_without_credentials(monkeypatch):
    from app.aggregators import adzuna

    monkeypatch.setattr(adzuna.settings, "adzuna_app_id", "")
    monkeypatch.setattr(adzuna.settings, "adzuna_app_key", "")

    assert await adzuna.fetch_adzuna() == []


@pytest.mark.asyncio
async def test_adzuna_fetch_maps_results(monkeypatch):
    from app.aggregators import adzuna
    from app.models import LocationType

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "id": "abc123",
                        "title": "Senior Product Manager",
                        "company": {"display_name": "Acme"},
                        "location": {"display_name": "New York, NY"},
                        "redirect_url": "https://adzuna.example/job/abc123",
                        "created": "2026-07-05T12:34:56Z",
                        "description": "<p>Own roadmap and analytics. 5+ years.</p>",
                        "salary_min": 120000,
                        "salary_max": "160000",
                        "contract_time": "full_time",
                        "contract_type": "permanent",
                        "category": {"label": "Product Jobs"},
                    },
                    {
                        "id": "missing-title",
                        "company": {"display_name": "Acme"},
                        "redirect_url": "https://adzuna.example/job/missing-title",
                    },
                ]
            }

    calls = []

    async def fake_get(url, *, params=None):
        calls.append((url, params))
        return FakeResponse()

    monkeypatch.setattr(adzuna.settings, "adzuna_app_id", "app-id")
    monkeypatch.setattr(adzuna.settings, "adzuna_app_key", "app-key")
    monkeypatch.setattr(adzuna.http, "get", fake_get)

    jobs = await adzuna.fetch_adzuna(max_jobs=1)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.external_id == "abc123"
    assert job.title == "Senior Product Manager"
    assert job.company_name == "Acme"
    assert job.location_raw == "New York, NY"
    assert job.location_type == LocationType.onsite
    assert job.is_us is True
    assert job.salary_min == 120000
    assert job.salary_max == 160000
    assert job.salary_currency == "USD"
    assert job.min_experience == 5
    assert job.max_experience is None
    assert job.employment_type == "full time / permanent / Product Jobs"
    assert "analytics" in job.skills
    assert calls[0][1]["app_id"] == "app-id"
    assert calls[0][1]["app_key"] == "app-key"


def _job(company, ext):
    return NormalizedJob(
        external_id=ext, title="Product Manager", apply_url=f"https://m/{ext}",
        company_name=company, location_raw="New York, NY", is_us=True,
    )


@pytest.mark.asyncio
async def test_ingest_source_groups_and_creates_companies(session):
    jobs = [_job("Acme", "1"), _job("Acme", "2"), _job("Globex", "3")]
    stats = await ingest_source(session, ATSProvider.themuse, jobs)

    assert stats == {"employers": 2, "jobs": 3, "new": 3}
    companies = (await session.execute(select(Company))).scalars().all()
    assert {c.name for c in companies} == {"Acme", "Globex"}
    # Slugs are provider-suffixed so they can't collide with a real ATS row.
    assert all(c.slug.endswith("-themuse") for c in companies)
    assert all(c.ats_provider == ATSProvider.themuse for c in companies)
    assert len((await session.execute(select(Job))).scalars().all()) == 3


@pytest.mark.asyncio
async def test_aggregator_does_not_close_on_partial_slice(session):
    # First run brings 2 Acme jobs; a later slice with only 1 must NOT close the other.
    await ingest_source(session, ATSProvider.themuse, [_job("Acme", "1"), _job("Acme", "2")])
    await ingest_source(session, ATSProvider.themuse, [_job("Acme", "1")])
    from app.models import JobStatus
    open_jobs = (
        await session.execute(select(Job).where(Job.status == JobStatus.open))
    ).scalars().all()
    assert len(open_jobs) == 2  # nothing closed
