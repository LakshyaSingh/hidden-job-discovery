"""Crawl orchestration: iterate companies, dispatch to the right scraper,
hand results to ingest, and record a CrawlRun for observability.

Companies are crawled concurrently, each on its own session. The per-company
unit of work is intentionally self-contained so it can later become a queue
task with no changes to ingest.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import SessionLocal
from app.models import Company, CrawlRun
from app.scrapers.base import CompanyRef, get_scraper, supported_providers
from app.services.ingest import ingest_jobs

logger = logging.getLogger(__name__)
settings = get_settings()

# Consecutive "board is gone" responses before a company is deactivated. At an
# hourly crawl this is a few hours of a board being definitively absent, which
# no live board does.
DEAD_BOARD_THRESHOLD = 5

# Statuses that mean the board no longer exists, as opposed to the ATS having a
# bad minute. Only these retire a company.
_GONE_STATUSES = {404, 410}


def _is_board_gone(exc: BaseException) -> bool:
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response is not None
        and exc.response.status_code in _GONE_STATUSES
    )


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
        if company.consecutive_missing:
            # The board answered, so whatever made it 404 before is over.
            company.consecutive_missing = 0
    except Exception as exc:  # noqa: BLE001 — record & continue to next company
        logger.exception("crawl failed for %s", company.name)
        # Roll back the poisoned transaction so the next company (and the
        # CrawlRun write below) start from a clean session.
        await session.rollback()
        run = await session.merge(run)
        company = await session.merge(company)
        run.ok = False
        run.error = str(exc)[:2000]

        if _is_board_gone(exc):
            company.consecutive_missing += 1
            if company.consecutive_missing >= DEAD_BOARD_THRESHOLD:
                company.active = False
                logger.warning(
                    "deactivating %s (%s/%s): board gone for %d consecutive crawls",
                    company.name,
                    company.ats_provider.value,
                    company.ats_identifier,
                    company.consecutive_missing,
                )
    finally:
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
    return run


async def _crawl_one(
    company_id: int,
    sem: asyncio.Semaphore,
    session_factory: Callable[[], AsyncSession],
) -> CrawlRun | None:
    """Crawl one company on a session of its own.

    A session is not safe to share across concurrent tasks, so each company
    gets one. The semaphore bounds how many are open at once, which matters on
    a small managed Postgres where the connection limit is low.
    """
    async with sem:
        async with session_factory() as session:
            company = await session.get(Company, company_id)
            if company is None:  # deleted between listing and crawling
                return None
            return await crawl_company(session, company)


async def crawl_all(
    session: AsyncSession,
    *,
    session_factory: Callable[[], AsyncSession] | None = None,
) -> list[CrawlRun]:
    """Crawl every active company that a registered scraper can actually fetch.

    The provider filter is load-bearing. Aggregator ingestion creates a Company
    row per employer in a feed (adzuna, themuse, jobicy, remotive), and those
    providers have no scraper by design — the jobs arrive through
    services/aggregate.py instead. Without the filter every one of them is
    dispatched here, raises KeyError from get_scraper, and costs a failed
    CrawlRun row plus two round trips. In production that was 1,243 of 1,409
    companies and about a third of the wall time of every crawl.

    `session_factory` exists so tests can supply their own engine; production
    callers leave it unset.
    """
    factory = session_factory or SessionLocal
    crawlable = supported_providers()

    company_ids = (
        await session.execute(
            select(Company.id).where(
                Company.active.is_(True),
                Company.ats_provider.in_(crawlable),
            )
        )
    ).scalars().all()

    logger.info(
        "crawling %d companies across %d providers, concurrency %d",
        len(company_ids),
        len(crawlable),
        settings.crawl_concurrency,
    )

    sem = asyncio.Semaphore(settings.crawl_concurrency)
    results = await asyncio.gather(
        *(_crawl_one(cid, sem, factory) for cid in company_ids),
        return_exceptions=True,
    )

    runs: list[CrawlRun] = []
    for result in results:
        if isinstance(result, BaseException):
            # crawl_company swallows scraper failures, so reaching here means
            # the session itself failed. Log and keep the rest of the sweep.
            logger.error("crawl task crashed", exc_info=result)
        elif result is not None:
            runs.append(result)
    return runs
