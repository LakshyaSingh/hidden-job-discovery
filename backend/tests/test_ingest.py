"""End-to-end ingest/dedup tests against a real SQLite database.

Exercises the ORM + ingest service together: newness windows, the
source-of-truth posting date across a cross-source duplicate, change detection,
and removal detection.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import ATSProvider, Company, Job, JobStatus
from app.scrapers.base import NormalizedJob
from app.services.ingest import ingest_jobs


def _now():
    return datetime.now(timezone.utc)


async def _company(session, name="Stripe", token="stripe"):
    c = Company(
        name=name, slug=token, ats_provider=ATSProvider.greenhouse,
        ats_identifier=token, careers_url="https://x/careers",
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


@pytest.mark.asyncio
async def test_new_job_flagged_and_persisted(session):
    company = await _company(session)
    jobs = [
        NormalizedJob(
            external_id="1", title="Product Manager", apply_url="https://x/1",
            company_name="Stripe", location_raw="Remote, US",
            original_posted_at=_now(),
        )
    ]
    stats = await ingest_jobs(session, company, jobs)
    assert stats.new == 1
    row = (await session.execute(select(Job))).scalar_one()
    assert row.is_new is True
    assert row.status == JobStatus.open
    assert row.title_normalized == "product manager"


@pytest.mark.asyncio
async def test_old_posting_is_not_new(session):
    company = await _company(session)
    jobs = [
        NormalizedJob(
            external_id="2", title="Data Analyst", apply_url="https://x/2",
            company_name="Stripe", location_raw="NYC",
            original_posted_at=_now() - timedelta(days=30),
        )
    ]
    await ingest_jobs(session, company, jobs)
    row = (await session.execute(select(Job))).scalar_one()
    assert row.is_new is False  # 30 days old → not new despite first discovery now


@pytest.mark.asyncio
async def test_source_of_truth_keeps_oldest_date(session):
    """A cross-source duplicate (same fingerprint) reposted with a FRESH date must
    not override the older authoritative date — the old job stays old."""
    company = await _company(session)
    old = _now() - timedelta(days=20)
    await ingest_jobs(session, company, [
        NormalizedJob(external_id="10", title="Sr. PM", apply_url="https://x/10",
                      company_name="Stripe", location_raw="Remote",
                      original_posted_at=old)
    ])
    # Second "source": same company+title+location => same fingerprint, but a
    # brand-new posting date (as an aggregator repost would claim).
    company2 = await _company(session, name="Stripe", token="stripe-lever")
    await ingest_jobs(session, company2, [
        NormalizedJob(external_id="99", title="Senior Product Manager",
                      apply_url="https://x/99", company_name="Stripe",
                      location_raw="Remote, US", original_posted_at=_now())
    ])
    rows = (await session.execute(select(Job).where(Job.external_id == "99"))).scalars().all()
    dup = rows[0]
    # It inherited the older authoritative date and is therefore NOT new.
    assert dup.original_posted_at.replace(tzinfo=timezone.utc) <= old + timedelta(seconds=1)
    assert dup.is_new is False


@pytest.mark.asyncio
async def test_unchanged_then_removed(session):
    company = await _company(session)
    job = NormalizedJob(external_id="5", title="PM", apply_url="https://x/5",
                        company_name="Stripe", location_raw="Remote",
                        original_posted_at=_now())
    s1 = await ingest_jobs(session, company, [job])
    assert s1.new == 1
    # Re-crawl, identical content → unchanged, not new insert.
    s2 = await ingest_jobs(session, company, [job])
    assert s2.new == 0 and s2.unchanged == 1
    # A healthy sweep that still returns jobs but omits #5 → #5 is closed.
    other = NormalizedJob(external_id="6", title="PM Two", apply_url="https://x/6",
                          company_name="Stripe", location_raw="Remote",
                          original_posted_at=_now())
    s3 = await ingest_jobs(session, company, [other])
    assert s3.closed == 1
    row5 = (
        await session.execute(select(Job).where(Job.external_id == "5"))
    ).scalar_one()
    assert row5.status == JobStatus.closed


@pytest.mark.asyncio
async def test_oversized_fields_are_clamped(session):
    company = await _company(session)
    job = NormalizedJob(
        external_id="9", title="X" * 600, apply_url="https://x/9",
        company_name="Stripe", location_raw="Y" * 800, original_posted_at=_now(),
    )
    s = await ingest_jobs(session, company, [job])
    assert s.new == 1
    row = (
        await session.execute(select(Job).where(Job.external_id == "9"))
    ).scalar_one()
    assert len(row.title) <= 512 and len(row.location_raw) <= 512


@pytest.mark.asyncio
async def test_empty_fetch_does_not_close(session):
    """A fetch returning 0 jobs is treated as a suspected partial/failed fetch
    and must NOT close the board (this was causing count fluctuation)."""
    company = await _company(session)
    job = NormalizedJob(external_id="7", title="PM", apply_url="https://x/7",
                        company_name="Stripe", location_raw="Remote",
                        original_posted_at=_now())
    await ingest_jobs(session, company, [job])
    s = await ingest_jobs(session, company, [])
    assert s.closed == 0
    row = (
        await session.execute(select(Job).where(Job.external_id == "7"))
    ).scalar_one()
    assert row.status == JobStatus.open


async def test_recrawl_never_reads_the_description_column(session):
    """Egress guard, invisible to behavioural tests.

    Every crawl re-reads every posting it already has, and the stale-close
    sweep re-reads every open posting per company. When those selected whole
    rows they dragged the description text back out of the database each time,
    which on a managed Postgres is billed egress and reached gigabytes a day.
    description is written but never read, so nothing should ever select it.
    """
    from sqlalchemy import event

    company = Company(
        name="Acme", slug="acme", ats_provider=ATSProvider.greenhouse,
        ats_identifier="acme",
    )
    session.add(company)
    await session.commit()

    posting = NormalizedJob(
        external_id="j1",
        title="Software Engineer",
        apply_url="https://example.com/j1",
        company_name="Acme",
        location_raw="Austin, TX",
        description="x" * 20_000,
    )
    await ingest_jobs(session, company, [posting])

    selects: list[str] = []
    engine = session.sync_session.get_bind()

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    try:
        # Re-crawl: same posting, unchanged, plus one that vanished.
        await ingest_jobs(session, company, [posting])
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert selects, "expected the re-crawl to query something"

    # Nothing may read the description text.
    offenders = [s for s in selects if "description" in s.lower()]
    assert not offenders, (
        "a SELECT still reads jobs.description:\n" + "\n".join(offenders)
    )

    # Nor any of the other wide columns. These are written on every sighting
    # but never read, and a crawl re-reads the whole corpus, so each one costs
    # its width times the number of postings, every hour.
    for column in ("apply_url", "careers_url", "location_raw", "skills",
                   "title_normalized"):
        leaking = [s for s in selects if f"jobs.{column}" in s.lower()]
        assert not leaking, (
            f"a SELECT still reads jobs.{column}:\n" + "\n".join(leaking)
        )
