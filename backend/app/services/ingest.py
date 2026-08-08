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

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

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
    session: AsyncSession,
    company: Company,
    jobs: list[NormalizedJob],
    *,
    close_stale: bool = True,
) -> IngestStats:
    """Upsert a company's current postings and close ones that vanished.

    close_stale=False for aggregator sources, which fetch only a slice of a
    company's jobs per run (so "not seen this run" doesn't mean "removed")."""
    stats = IngestStats(seen=len(jobs))
    now = _now()
    new_cutoff = now - timedelta(hours=settings.new_job_window_hours)
    seen_external_ids: set[str] = set()

    for nj in jobs:
        # Clamp to column limits so one oversized field can't abort the batch.
        nj.external_id = nj.external_id[:255]
        nj.title = (nj.title or "")[:512]
        if nj.location_raw:
            nj.location_raw = nj.location_raw[:512]
        if nj.apply_url:
            nj.apply_url = nj.apply_url[:1024]
        if nj.employment_type:
            nj.employment_type = nj.employment_type[:64]

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

        # description is deferred: it is the largest column in the table and is
        # only ever assigned below, never read. Change detection compares
        # content_hash instead. Loading it here meant every crawl dragged every
        # posting's full text back out of the database for nothing.
        existing = (
            await session.execute(
                select(Job)
                .where(
                    Job.company_id == company.id,
                    Job.external_id == nj.external_id,
                )
                .options(defer(Job.description))
            )
        ).scalar_one_or_none()

        # Country (scraper knows best; otherwise infer from the location text).
        is_us = (
            nj.is_us if nj.is_us is not None
            else extract.is_us_location(nj.location_raw)
        )
        # Experience: prefer the scraper's parsed range; fall back to seniority
        # implied by the title so filters aren't defeated by missing data.
        min_exp, max_exp = nj.min_experience, nj.max_experience
        if min_exp is None and max_exp is None:
            min_exp, max_exp = extract.infer_experience_from_title(nj.title)

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
                    is_us=is_us,
                    ats_provider=company.ats_provider,
                    apply_url=nj.apply_url,
                    careers_url=company.careers_url,
                    first_discovered_at=now,
                    original_posted_at=posted_at,
                    date_source=date_source,
                    last_checked_at=now,
                    last_seen_at=now,
                    min_experience=min_exp,
                    max_experience=max_exp,
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
        # Backfill country + experience on every sighting (cheap; also upgrades
        # rows created before these fields existed).
        existing.is_us = is_us
        if existing.min_experience is None and existing.max_experience is None:
            existing.min_experience, existing.max_experience = min_exp, max_exp
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
        existing.min_experience = min_exp
        existing.max_experience = max_exp
        existing.salary_min = nj.salary_min
        existing.salary_max = nj.salary_max
        existing.content_hash = chash
        existing.content_fingerprint = fingerprint
        stats.updated += 1

    # Removal detection: any previously-open job for this company not seen this
    # sweep is now closed. Guard against a partial/failed fetch (a transient
    # error or rate-limit) wiping the board: if this run saw far fewer jobs than
    # we currently have open, skip closing and keep the existing rows.
    # Only the identifier columns are needed to decide what to close. Selecting
    # whole rows pulled every open posting's description out of the database on
    # every single crawl, for every company, which is what put the egress bill
    # into gigabytes a day.
    open_rows = (
        await session.execute(
            select(Job.id, Job.external_id).where(
                Job.company_id == company.id, Job.status == JobStatus.open
            )
        )
    ).all()
    open_count = len(open_rows)
    suspicious = stats.seen == 0 or (open_count > 4 and stats.seen < open_count * 0.5)
    if not close_stale:
        pass  # aggregator slice — never infer removal from a partial view
    elif suspicious:
        logger.warning(
            "ingest %s: fetched only %d job(s) but %d are open — skipping "
            "stale-close (suspected partial fetch)",
            company.name, stats.seen, open_count,
        )
    else:
        stale_ids = [
            job_id
            for job_id, external_id in open_rows
            if external_id not in seen_external_ids
        ]
        if stale_ids:
            # A set-based UPDATE rather than mutating loaded objects. These
            # rows were not seen this sweep, so none of them is in the session
            # and nothing needs synchronizing back.
            result = await session.execute(
                update(Job)
                .where(Job.id.in_(stale_ids))
                .values(status=JobStatus.closed, is_new=False)
                .execution_options(synchronize_session=False)
            )
            stats.closed = result.rowcount or len(stale_ids)

    await session.commit()
    logger.info(
        "ingest %s: seen=%d new=%d updated=%d unchanged=%d closed=%d",
        company.name, stats.seen, stats.new, stats.updated,
        stats.unchanged, stats.closed,
    )
    return stats
