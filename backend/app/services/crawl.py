"""Crawl orchestration: iterate companies, dispatch to the right scraper,
hand results to ingest, and record a CrawlRun for observability.

Phase 1 runs in-process. The per-company unit of work is intentionally
self-contained so it can later become a queue task with no changes to ingest.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, CrawlRun
from app.scrapers.base import CompanyRef, get_scraper
from app.services.ingest import ingest_jobs

logger = logging.getLogger(__name__)


async def crawl_company(session: AsyncSession, company: Company) -> CrawlRun:
    run = CrawlRun(company_id=company.id, provider=company.ats_provider)
    session.add(run)
    await session.commit()

    try:
        scraper = get_scraper(company.ats_provider)
        ref = CompanyRef(
            name=company.name,
            ats_identifier=company.ats_identifier,
            careers_url=company.careers_url,
        )
        jobs = await scraper.fetch_jobs(ref)
        stats = await ingest_jobs(session, company, jobs)
        run.jobs_seen = stats.seen
        run.jobs_new = stats.new
        run.jobs_updated = stats.updated
        run.jobs_closed = stats.closed
        run.ok = True
    except Exception as exc:  # noqa: BLE001 — record & continue to next company
        logger.exception("crawl failed for %s", company.name)
        # Roll back the poisoned transaction so the next company (and the
        # CrawlRun write below) start from a clean session.
        await session.rollback()
        run = await session.merge(run)
        run.ok = False
        run.error = str(exc)[:2000]
    finally:
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
    return run


async def crawl_all(session: AsyncSession) -> list[CrawlRun]:
    companies = (
        await session.execute(select(Company).where(Company.active.is_(True)))
    ).scalars().all()
    runs = []
    for company in companies:
        runs.append(await crawl_company(session, company))
    return runs
