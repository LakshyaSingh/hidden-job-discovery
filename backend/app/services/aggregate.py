"""Aggregator ingestion.

Aggregator sources (e.g. The Muse) return jobs from many employers in one feed.
We group by employer, get-or-create a Company for each, and reuse the normal
ingest pipeline (dedup, is_us, experience, is_new). Stale-closing is disabled:
a run only sees a slice of a company's jobs, so "not seen" != "removed". The
cross-source fingerprint means a job also found via a company's real ATS is
deduped, with the ATS keeping source-of-truth for the posting date.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aggregators.adzuna import fetch_adzuna
from app.aggregators.jobicy import fetch_jobicy
from app.aggregators.remotive import fetch_remotive
from app.aggregators.themuse import fetch_themuse
from app.models import ATSProvider, Company
from app.scrapers.base import NormalizedJob
from app.services.ingest import ingest_jobs

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


async def _get_or_create_company(
    session: AsyncSession, provider: ATSProvider, name: str
) -> Company:
    identifier = _slugify(name) or name.lower()
    existing = (
        await session.execute(
            select(Company).where(
                Company.ats_provider == provider,
                Company.ats_identifier == identifier,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    company = Company(
        name=name,
        # Suffix keeps the slug unique vs. the same employer's real ATS row.
        slug=f"{identifier}-{provider.value}",
        ats_provider=provider,
        ats_identifier=identifier,
        active=True,
    )
    session.add(company)
    await session.flush()
    return company


async def ingest_source(
    session: AsyncSession, provider: ATSProvider, jobs: list[NormalizedJob]
) -> dict:
    by_company: dict[str, list[NormalizedJob]] = defaultdict(list)
    for nj in jobs:
        by_company[nj.company_name].append(nj)

    companies = new_jobs = 0
    for name, njs in by_company.items():
        company = await _get_or_create_company(session, provider, name)
        companies += 1
        stats = await ingest_jobs(session, company, njs, close_stale=False)
        new_jobs += stats.new
    stats = {"employers": companies, "jobs": len(jobs), "new": new_jobs}
    logger.info(
        "aggregate %s: employers=%d jobs=%d new=%d",
        provider.value, stats["employers"], stats["jobs"], stats["new"],
    )
    return stats


# Registry of aggregator sources: (provider, fetch fn). Add a source here.
_AGGREGATORS = [
    (ATSProvider.themuse, fetch_themuse),
    (ATSProvider.remotive, fetch_remotive),
    (ATSProvider.jobicy, fetch_jobicy),
    (ATSProvider.adzuna, fetch_adzuna),
]


async def run_aggregators(session: AsyncSession) -> dict:
    """Run every aggregator source; isolate failures so one dead feed can't
    stop the others."""
    out: dict = {}
    for provider, fetch in _AGGREGATORS:
        try:
            jobs = await fetch()
            out[provider.value] = await ingest_source(session, provider, jobs)
        except Exception:  # noqa: BLE001 — a flaky feed shouldn't abort the rest
            logger.exception("aggregator %s failed", provider.value)
            await session.rollback()
            out[provider.value] = {"error": True}
    return out
