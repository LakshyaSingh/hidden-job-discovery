"""Adzuna aggregator source — broad US job search feed.

    GET https://api.adzuna.com/v1/api/jobs/us/search/{page}

Requires ADZUNA_APP_ID and ADZUNA_APP_KEY. The US endpoint limits results to
the United States market; each result carries employer, location, redirect URL,
posting date, salary, and description fields.
"""
from __future__ import annotations

import logging

from app.config import get_settings
from app.models import LocationType
from app.scrapers import extract, http
from app.scrapers.base import NormalizedJob

logger = logging.getLogger(__name__)
settings = get_settings()

_URL = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"
_PER_PAGE = 50


def _employment_type(job: dict) -> str | None:
    parts = [
        job.get("contract_time"),
        job.get("contract_type"),
        (job.get("category") or {}).get("label"),
    ]
    text = " / ".join(str(p).replace("_", " ") for p in parts if p)
    return text or None


def _location_raw(job: dict) -> str | None:
    location = job.get("location") or {}
    display = location.get("display_name")
    if display:
        return display
    area = location.get("area")
    if isinstance(area, list) and area:
        return ", ".join(str(part) for part in area if part)
    return None


def _salary(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_adzuna(max_jobs: int | None = None) -> list[NormalizedJob]:
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        logger.info("adzuna: missing credentials; skipping")
        return []

    limit = max_jobs if max_jobs is not None else settings.adzuna_max_jobs
    if limit <= 0:
        return []

    results: list[NormalizedJob] = []
    pages = (limit + _PER_PAGE - 1) // _PER_PAGE
    for page in range(1, pages + 1):
        resp = await http.get(
            _URL.format(page=page),
            params={
                "app_id": settings.adzuna_app_id,
                "app_key": settings.adzuna_app_key,
                "results_per_page": min(_PER_PAGE, limit - len(results)),
                "sort_by": "date",
                "content-type": "application/json",
            },
        )
        if resp.status_code != 200:
            break
        payload = resp.json()
        rows = payload.get("results") or []
        if not rows:
            break

        for job in rows:
            company = (job.get("company") or {}).get("display_name")
            external_id = job.get("id")
            title = (job.get("title") or "").strip()
            url = job.get("redirect_url")
            if not external_id or not company or not title or not url:
                continue

            location_raw = _location_raw(job)
            description = extract.html_to_text(job.get("description"))
            min_exp, max_exp = extract.extract_experience(description)
            salary_min = _salary(job.get("salary_min"))
            salary_max = _salary(job.get("salary_max"))

            results.append(
                NormalizedJob(
                    external_id=str(external_id),
                    title=title,
                    apply_url=url,
                    company_name=company.strip(),
                    location_raw=location_raw,
                    location_type=(
                        LocationType.remote
                        if "remote" in f"{title} {location_raw or ''}".lower()
                        else extract.classify_location(location_raw)
                    ),
                    is_us=True,
                    original_posted_at=extract.parse_iso_datetime(job.get("created")),
                    employment_type=_employment_type(job),
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency="USD" if salary_min or salary_max else None,
                    description=description,
                    skills=extract.extract_skills(description),
                    min_experience=min_exp,
                    max_experience=max_exp,
                )
            )
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    logger.info("adzuna: fetched %d US jobs", len(results))
    return results
