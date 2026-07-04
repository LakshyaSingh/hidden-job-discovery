"""Tests for aggregator ingestion (network mocked)."""
import pytest
from sqlalchemy import select

from app.models import ATSProvider, Company, Job
from app.scrapers.base import NormalizedJob
from app.services.aggregate import _slugify, ingest_source


def test_slugify():
    assert _slugify("Modern Treasury") == "modern-treasury"
    assert _slugify("AT&T, Inc.") == "at-t-inc"


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
