"""Ingestion: turn NormalizedJob objects into persisted, deduplicated rows.

Implements the source-of-truth and newness rules from ARCHITECTURE.md §5:
  * same-source dedup via (company_id, external_id)
  * cross-source dedup via content_fingerprint, keeping the OLDEST posting date
  * change detection via content_hash (skip re-parsing unchanged postings)
  * is_new only on genuine first discovery, within the configured window
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Company, DateSource, Job, JobStatus
from app.scrapers import extract
from app.scrapers.base import NormalizedJob

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class IngestStats:
    seen: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    closed: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """Normalize a datetime to UTC-aware. Some backends (e.g. SQLite) return
    naive datetimes even for timezone=True columns; treat those as UTC so
    comparisons against tz-aware cutoffs never raise."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def _authoritative_posted_at(
    session: AsyncSession, fingerprint: str, incoming: datetime | None
) -> tuple[datetime | None, DateSource]:
    """Resolve the true original posting date.

    The company portal is the source of truth. If another row shares this
    fingerprint (same job seen elsewhere / reposted), keep the OLDEST known
    posting date so an aggregator's fresher repost can't make an old job look new.
    """
    date_source = DateSource.ats if incoming else DateSource.discovered
    candidate = incoming

    existing_dates = (
        await session.execute(
            select(Job.original_posted_at).where(
                Job.content_fingerprint == fingerprint,
                Job.original_posted_at.is_not(None),
            )
        )
    ).scalars().all()

    for d in existing_dates:
        d = _aware(d)
        if candidate is None or d < _aware(candidate):
            candidate = d
            date_source = DateSource.ats
    return candidate, date_source


async def ingest_jobs(
    session: AsyncSession, company: Company, jobs: list[NormalizedJob]
) -> IngestStats:
    """Upsert a company's current postings and close ones that vanished."""
    stats = IngestStats(seen=len(jobs))
    now = _now()
    new_cutoff = now - timedelta(hours=settings.new_job_window_hours)
    seen_external_ids: set[str] = set()

    for nj in jobs:
        seen_external_ids.add(nj.external_id)
        fingerprint = extract.content_fingerprint(
            company.name, nj.title, nj.location_raw
        )
        chash = extract.content_hash(
            title=nj.title,
            location_raw=nj.location_raw,
            description=nj.description,
            salary_min=nj.salary_min,
            salary_max=nj.salary_max,
        )

        existing = (
            await session.execute(
                select(Job).where(
                    Job.company_id == company.id,
                    Job.external_id == nj.external_id,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            posted_at, date_source = await _authoritative_posted_at(
                session, fingerprint, nj.original_posted_at
            )
            # New to us. "New" only if its authoritative posting date is recent
            # (or we have no date and just discovered it).
            effective_date = posted_at or now
            is_new = effective_date >= new_cutoff

            session.add(
                Job(
                    company_id=company.id,
                    external_id=nj.external_id,
                    title=nj.title,
                    title_normalized=extract.normalize_title(nj.title),
                    location_raw=nj.location_raw,
                    location_type=nj.location_type,
                    ats_provider=company.ats_provider,
                    apply_url=nj.apply_url,
                    careers_url=company.careers_url,
                    first_discovered_at=now,
                    original_posted_at=posted_at,
                    date_source=date_source,
                    last_checked_at=now,
                    last_seen_at=now,
                    min_experience=nj.min_experience,
                    max_experience=nj.max_experience,
                    employment_type=nj.employment_type,
                    salary_min=nj.salary_min,
                    salary_max=nj.salary_max,
                    salary_currency=nj.salary_currency,
                    description=nj.description,
                    skills=nj.skills,
                    content_fingerprint=fingerprint,
                    content_hash=chash,
                    status=JobStatus.open,
                    is_new=is_new,
                )
            )
            stats.new += 1
            continue

        # Existing row: always refresh liveness timestamps.
        existing.last_checked_at = now
        existing.last_seen_at = now
        existing.status = JobStatus.open
        # Expire the is_new flag once outside the window.
        if existing.is_new:
            effective_date = _aware(
                existing.original_posted_at or existing.first_discovered_at
            )
            if effective_date < new_cutoff:
                existing.is_new = False

        if existing.content_hash == chash:
            stats.unchanged += 1
            continue

        # Content actually changed → re-apply mutable fields (cheap re-parse).
        existing.title = nj.title
        existing.title_normalized = extract.normalize_title(nj.title)
        existing.location_raw = nj.location_raw
        existing.location_type = nj.location_type
        existing.apply_url = nj.apply_url
        existing.description = nj.description
        existing.skills = nj.skills
        existing.min_experience = nj.min_experience
        existing.max_experience = nj.max_experience
        existing.salary_min = nj.salary_min
        existing.salary_max = nj.salary_max
        existing.content_hash = chash
        existing.content_fingerprint = fingerprint
        stats.updated += 1

    # Removal detection: any previously-open job for this company not seen this
    # sweep is now closed.
    open_jobs = (
        await session.execute(
            select(Job).where(
                Job.company_id == company.id, Job.status == JobStatus.open
            )
        )
    ).scalars().all()
    for job in open_jobs:
        if job.external_id not in seen_external_ids:
            job.status = JobStatus.closed
            job.is_new = False
            stats.closed += 1

    await session.commit()
    logger.info(
        "ingest %s: seen=%d new=%d updated=%d unchanged=%d closed=%d",
        company.name, stats.seen, stats.new, stats.updated,
        stats.unchanged, stats.closed,
    )
    return stats
