"""Job query, detail, and user-state endpoints — powers the dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models import (
    ATSProvider,
    Company,
    Job,
    JobStatus,
    JobUserState,
    LocationType,
)
from app.scrapers.extract import normalize_title
from app.services.matching import expand_query
from app.schemas import (
    JobDetailOut,
    JobListOut,
    JobOut,
    UserStateOut,
    UserStateUpdate,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_POSTED_WINDOWS = {"24h": 24, "48h": 48, "7d": 24 * 7}
SortField = Literal["posted", "discovered", "title", "company"]


@router.get("", response_model=JobListOut)
async def list_jobs(
    session: AsyncSession = Depends(get_session),
    q: str | None = Query(None, description="fuzzy title/keyword match"),
    min_experience: int | None = None,
    max_experience: int | None = None,
    location_type: LocationType | None = None,
    provider: ATSProvider | None = None,
    us_only: bool = True,
    posted_within: Literal["24h", "48h", "7d"] | None = None,
    status: JobStatus = JobStatus.open,
    only_new: bool = False,
    discovered_today: bool = False,
    bookmarked: bool | None = None,
    applied: bool | None = None,
    include_hidden: bool = False,
    sort: SortField = "posted",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> JobListOut:
    now = datetime.now(timezone.utc)
    stmt = (
        select(Job)
        .join(Company)
        .outerjoin(JobUserState)
        .options(selectinload(Job.company), selectinload(Job.user_state))
    )

    stmt = stmt.where(Job.status == status)

    # --- Title match. If the query maps to a role family (e.g. "product
    # manager" → also "product lead", "group PM", "head of product"), OR-match
    # every alias in that family. Otherwise require all query tokens (AND). ---
    if q:
        phrases = expand_query(q)
        if len(phrases) > 1:  # taxonomy expanded the query beyond itself
            stmt = stmt.where(
                or_(*[Job.title_normalized.ilike(f"%{p}%") for p in phrases])
            )
        else:
            for token in normalize_title(q).split():
                stmt = stmt.where(Job.title_normalized.ilike(f"%{token}%"))

    # --- Experience overlap: a job [jmin, jmax] matches filter [fmin, fmax] if
    # the ranges overlap. Jobs with no extracted experience are included so we
    # never hide a potentially-relevant posting on missing data. ---
    if min_experience is not None:
        stmt = stmt.where(
            or_(Job.max_experience.is_(None), Job.max_experience >= min_experience)
        )
    if max_experience is not None:
        stmt = stmt.where(
            or_(Job.min_experience.is_(None), Job.min_experience <= max_experience)
        )

    if location_type is not None:
        stmt = stmt.where(Job.location_type == location_type)
    if provider is not None:
        stmt = stmt.where(Job.ats_provider == provider)
    # US-only by default (the product's scope). Excludes jobs known to be
    # non-US and those whose country could not be determined.
    if us_only:
        stmt = stmt.where(Job.is_us.is_(True))

    if posted_within is not None:
        cutoff = now - timedelta(hours=_POSTED_WINDOWS[posted_within])
        # Use authoritative posting date when we have it; fall back to discovery.
        stmt = stmt.where(
            func.coalesce(Job.original_posted_at, Job.first_discovered_at) >= cutoff
        )

    if only_new:
        stmt = stmt.where(Job.is_new.is_(True))
    if discovered_today:
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = stmt.where(Job.first_discovered_at >= start_of_day)

    if not include_hidden:
        stmt = stmt.where(
            or_(JobUserState.hidden.is_(None), JobUserState.hidden.is_(False))
        )
    if bookmarked is not None:
        stmt = stmt.where(JobUserState.bookmarked.is_(bookmarked))
    if applied is not None:
        stmt = stmt.where(JobUserState.applied.is_(applied))

    # --- Total (before pagination) ---
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    # --- Sorting ---
    sort_col = {
        "posted": func.coalesce(Job.original_posted_at, Job.first_discovered_at),
        "discovered": Job.first_discovered_at,
        "title": Job.title_normalized,
        "company": Company.name,
    }[sort]
    stmt = stmt.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
    stmt = stmt.limit(limit).offset(offset)

    jobs = (await session.execute(stmt)).scalars().all()
    return JobListOut(total=total, items=[JobOut.model_validate(j) for j in jobs])


@router.get("/{job_id}", response_model=JobDetailOut)
async def get_job(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> JobDetailOut:
    job = (
        await session.execute(
            select(Job)
            .where(Job.id == job_id)
            .options(selectinload(Job.company), selectinload(Job.user_state))
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    return JobDetailOut.model_validate(job)


async def _get_or_create_state(session: AsyncSession, job_id: int) -> JobUserState:
    state = (
        await session.execute(
            select(JobUserState).where(JobUserState.job_id == job_id)
        )
    ).scalar_one_or_none()
    if state is None:
        exists = (
            await session.execute(select(Job.id).where(Job.id == job_id))
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(404, "job not found")
        state = JobUserState(job_id=job_id)
        session.add(state)
    return state


@router.patch("/{job_id}/state", response_model=UserStateOut)
async def update_state(
    job_id: int,
    payload: UserStateUpdate,
    session: AsyncSession = Depends(get_session),
) -> UserStateOut:
    state = await _get_or_create_state(session, job_id)
    if payload.bookmarked is not None:
        state.bookmarked = payload.bookmarked
    if payload.hidden is not None:
        state.hidden = payload.hidden
    if payload.applied is not None:
        state.applied = payload.applied
        state.applied_at = datetime.now(timezone.utc) if payload.applied else None
    await session.commit()
    await session.refresh(state)
    return UserStateOut.model_validate(state)
