"""Remotive aggregator source (free, no key) — remote jobs open to US applicants.

    GET https://remotive.com/api/remote-jobs?limit=N

We keep postings whose candidate_required_location indicates US eligibility
(USA / North America / Worldwide / Anywhere) and drop region-locked non-US ones
(Canada, Europe, LATAM, ...).
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

_URL = "https://remotive.com/api/remote-jobs"
# Location strings that mean "a US applicant can take this remote job".
_US_ELIGIBLE = ("usa", "united states", "u.s", "north america", "worldwide", "anywhere")


def _html_to_text(raw: str | None) -> str | None:
    if not raw:
        return None
    return html.unescape(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)) or None


def _us_eligible(location: str | None) -> bool:
    if not location:
        return False
    return any(m in location.lower() for m in _US_ELIGIBLE)


async def fetch_remotive(limit: int | None = None) -> list[NormalizedJob]:
    n = limit if limit is not None else settings.remotive_max_jobs
    resp = await http.get(_URL, params={"limit": n})
    if resp.status_code != 200:
        return []
    results: list[NormalizedJob] = []
    for j in resp.json().get("jobs", []):
        loc = j.get("candidate_required_location")
        if not _us_eligible(loc):
            continue
        company = j.get("company_name")
        url = j.get("url")
        if not company or not url:
            continue
        description = _html_to_text(j.get("description"))
        min_exp, max_exp = extract.extract_experience(description)
        results.append(
            NormalizedJob(
                external_id=str(j["id"]),
                title=(j.get("title") or "").strip(),
                apply_url=url,
                company_name=company.strip(),
                location_raw=f"Remote ({loc})",
                location_type=LocationType.remote,
                is_us=True,
                original_posted_at=extract.parse_iso_datetime(j.get("publication_date")),
                employment_type=j.get("job_type"),
                description=description,
                skills=extract.extract_skills(description),
                min_experience=min_exp,
                max_experience=max_exp,
            )
        )
    logger.info("remotive: %d US-eligible jobs", len(results))
    return results
