"""Pydantic request/response schemas for the API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import ATSProvider, DateSource, JobStatus, LocationType


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
    ats_provider: ATSProvider
    careers_url: str | None = None


class CompanyCreate(BaseModel):
    name: str
    slug: str
    ats_provider: ATSProvider
    ats_identifier: str
    careers_url: str | None = None


class UserStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    bookmarked: bool = False
    hidden: bool = False
    applied: bool = False
    applied_at: datetime | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    company: CompanyOut
    location_raw: str | None
    location_type: LocationType
    ats_provider: ATSProvider
    apply_url: str
    careers_url: str | None
    first_discovered_at: datetime
    original_posted_at: datetime | None
    date_source: DateSource
    last_checked_at: datetime
    min_experience: int | None
    max_experience: int | None
    employment_type: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    skills: list[str]
    status: JobStatus
    is_new: bool
    user_state: UserStateOut | None = None


class JobDetailOut(JobOut):
    description: str | None = None


class JobListOut(BaseModel):
    total: int
    items: list[JobOut]


class UserStateUpdate(BaseModel):
    bookmarked: bool | None = None
    hidden: bool | None = None
    applied: bool | None = None


class CrawlRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_id: int | None
    provider: ATSProvider
    started_at: datetime
    finished_at: datetime | None
    jobs_seen: int
    jobs_new: int
    jobs_updated: int
    jobs_closed: int
    ok: bool
    error: str | None
