"""Jobicy aggregator source (free, no key) — remote jobs, US-filtered server-side.

    GET https://jobicy.com/api/v2/remote-jobs?count=N&geo=usa

geo=usa means every result is US-eligible, so no client-side location filtering
is needed. Provides seniority (jobLevel) and salary.
"""
from __future__ import annotations

import html
import logging

from bs4 import BeautifulSoup

from app.config import get_settings
from app.scrapers import extract
from app.scrapers import http
from app.scrapers.base import NormalizedJob
from app.models import LocationType

logger = logging.getLogger(__name__)
settings = get_settings()

_URL = "https://jobicy.com/api/v2/remote-jobs"
_LEVEL_EXP = {
    "internship": (0, 1),
    "entry-level": (0, 2),
    "junior": (0, 2),
    "mid level": (2, 5),
    "mid-level": (2, 5),
    "senior": (5, None),
    "executive": (10, None),
    "director": (10, None),
}


def _html_to_text(raw: str | None) -> str | None:
    if not raw:
        return None
    return html.unescape(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)) or None


def _level_exp(level: str | None) -> tuple[int | None, int | None]:
    return _LEVEL_EXP.get((level or "").strip().lower(), (None, None))


async def fetch_jobicy(count: int | None = None) -> list[NormalizedJob]:
    n = count if count is not None else settings.jobicy_max_jobs
    resp = await http.get(_URL, params={"count": n, "geo": "usa"})
    if resp.status_code != 200:
        return []
    results: list[NormalizedJob] = []
    for j in resp.json().get("jobs", []):
        company = j.get("companyName")
        url = j.get("url")
        if not company or not url:
            continue
        description = _html_to_text(j.get("jobDescription") or j.get("jobExcerpt"))
        min_exp, max_exp = extract.extract_experience(description)
        if min_exp is None and max_exp is None:
            min_exp, max_exp = _level_exp(j.get("jobLevel"))
        job_type = j.get("jobType")
        if isinstance(job_type, list):
            job_type = job_type[0] if job_type else None
        results.append(
            NormalizedJob(
                external_id=str(j["id"]),
                title=(j.get("jobTitle") or "").strip(),
                apply_url=url,
                company_name=company.strip(),
                location_raw=f"Remote ({j.get('jobGeo') or 'USA'})",
                location_type=LocationType.remote,
                is_us=True,
                original_posted_at=extract.parse_iso_datetime(j.get("pubDate")),
                employment_type=job_type,
                salary_min=j.get("salaryMin") or None,
                salary_max=j.get("salaryMax") or None,
                salary_currency=j.get("salaryCurrency") or None,
                description=description,
                skills=extract.extract_skills(description),
                min_experience=min_exp,
                max_experience=max_exp,
            )
        )
    logger.info("jobicy: %d US jobs", len(results))
    return results
