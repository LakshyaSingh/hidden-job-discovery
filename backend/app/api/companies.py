"""Company management and crawl-trigger endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_key
from app.database import get_session
from app.models import Company
from app.scrapers.base import supported_providers
from app.schemas import CompanyCreate, CompanyOut, CrawlRunOut
from app.services.crawl import crawl_all, crawl_company

router = APIRouter(tags=["companies"])


@router.get("/providers", response_model=list[str])
async def list_providers() -> list[str]:
    """ATS providers that currently have a registered scraper."""
    return [p.value for p in supported_providers()]


@router.get("/companies", response_model=list[CompanyOut])
async def list_companies(session: AsyncSession = Depends(get_session)):
    companies = (await session.execute(select(Company))).scalars().all()
    return [CompanyOut.model_validate(c) for c in companies]


@router.post("/companies", response_model=CompanyOut, status_code=201)
async def create_company(
    payload: CompanyCreate,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin_key),
):
    company = Company(**payload.model_dump())
    session.add(company)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "company slug or ATS identifier already exists")
    await session.refresh(company)
    return CompanyOut.model_validate(company)


@router.post("/crawl", response_model=list[CrawlRunOut])
async def trigger_crawl(
    company_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin_key),
):
    """Trigger a crawl of one company (company_id) or all active companies.

    Synchronous in Phase 1. Phase 3 enqueues one task per company instead.
    """
    if company_id is not None:
        company = (
            await session.execute(select(Company).where(Company.id == company_id))
        ).scalar_one_or_none()
        if company is None:
            raise HTTPException(404, "company not found")
        run = await crawl_company(session, company)
        return [CrawlRunOut.model_validate(run)]
    runs = await crawl_all()
    return [CrawlRunOut.model_validate(r) for r in runs]
