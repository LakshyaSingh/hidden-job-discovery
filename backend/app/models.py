"""SQLAlchemy ORM models — the authoritative database schema.

See ARCHITECTURE.md §6 for the design rationale (dedup keys, source-of-truth
timestamps, change detection).

Note: SQLAlchemy resolves ``Mapped[...]`` annotations at class-creation time, so
these use ``Optional[X]`` (not ``X | None``) to stay compatible down to Python 3.9.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ATSProvider(str, enum.Enum):
    greenhouse = "greenhouse"
    lever = "lever"
    ashby = "ashby"
    smartrecruiters = "smartrecruiters"
    bamboohr = "bamboohr"
    jobvite = "jobvite"
    icims = "icims"
    workday = "workday"
    oracle = "oracle"
    successfactors = "successfactors"
    # Aggregator sources (not ATSes): jobs ingested from a broad job feed.
    themuse = "themuse"


class LocationType(str, enum.Enum):
    remote = "remote"
    hybrid = "hybrid"
    onsite = "onsite"
    unknown = "unknown"


class JobStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class DateSource(str, enum.Enum):
    """Where original_posted_at came from — authoritative vs. inferred."""

    ats = "ats"          # real publish date from the career portal (trusted)
    discovered = "discovered"  # we had no authoritative date; used first-seen


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    ats_provider: Mapped[ATSProvider] = mapped_column(Enum(ATSProvider), nullable=False)
    # Provider-specific identifier: Greenhouse board token, Lever site, etc.
    ats_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    careers_url: Mapped[Optional[str]] = mapped_column(String(1024))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    jobs: Mapped[List["Job"]] = relationship(back_populates="company")

    __table_args__ = (
        UniqueConstraint("ats_provider", "ats_identifier", name="uq_company_ats"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    # ATS-native id, unique within a company. Basis for same-source dedup.
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    title_normalized: Mapped[str] = mapped_column(String(512), nullable=False)

    location_raw: Mapped[Optional[str]] = mapped_column(String(512))
    location_type: Mapped[LocationType] = mapped_column(
        Enum(LocationType), default=LocationType.unknown, nullable=False
    )
    # True/False when known, NULL when the country could not be determined.
    is_us: Mapped[Optional[bool]] = mapped_column(Boolean)

    ats_provider: Mapped[ATSProvider] = mapped_column(Enum(ATSProvider), nullable=False)
    apply_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    careers_url: Mapped[Optional[str]] = mapped_column(String(1024))

    # --- Timestamps: source-of-truth logic lives here ---
    first_discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    original_posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    date_source: Mapped[DateSource] = mapped_column(
        Enum(DateSource), default=DateSource.discovered, nullable=False
    )
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # --- Extracted / structured fields ---
    min_experience: Mapped[Optional[int]] = mapped_column(Integer)
    max_experience: Mapped[Optional[int]] = mapped_column(Integer)
    employment_type: Mapped[Optional[str]] = mapped_column(String(64))
    salary_min: Mapped[Optional[float]] = mapped_column(Float)
    salary_max: Mapped[Optional[float]] = mapped_column(Float)
    salary_currency: Mapped[Optional[str]] = mapped_column(String(8))
    description: Mapped[Optional[str]] = mapped_column(Text)
    skills: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # --- Dedup & change detection ---
    # sha1 over normalized(company + title + location bucket): cross-source identity.
    content_fingerprint: Mapped[str] = mapped_column(String(40), nullable=False)
    # sha1 over description + key fields: skip re-parsing unchanged postings.
    content_hash: Mapped[str] = mapped_column(String(40), nullable=False)

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.open, nullable=False
    )
    is_new: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    company: Mapped["Company"] = relationship(back_populates="jobs")
    user_state: Mapped[Optional["JobUserState"]] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("company_id", "external_id", name="uq_job_company_external"),
        Index("ix_jobs_fingerprint", "content_fingerprint"),
        Index("ix_jobs_original_posted_at", "original_posted_at"),
        Index("ix_jobs_title_normalized", "title_normalized"),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_is_us", "is_us"),
    )


class JobUserState(Base):
    """Per-job user flags. Separate table so it survives re-crawls and scales to
    multiple users later (add user_id + composite PK)."""

    __tablename__ = "job_user_state"

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    bookmarked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )

    job: Mapped["Job"] = relationship(back_populates="user_state")


class SavedSearch(Base):
    """Persisted filter set. Powers the dashboard's saved searches and, later,
    notification triggers."""

    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    filters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    notify_daily: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notify_instant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CrawlRun(Base):
    """One row per company crawl — observability & incremental-crawl bookkeeping."""

    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL")
    )
    provider: Mapped[ATSProvider] = mapped_column(Enum(ATSProvider), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    jobs_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_closed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
