"""Greenhouse scraper (proof-of-concept provider).

Greenhouse exposes a stable public JSON board API — no browser needed:
    https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Each job carries id, title, location.name, absolute_url, updated_at, and (with
content=true) the full HTML description. `first_published` is used as the
authoritative posting date when present.
"""
from __future__ import annotations

import logging

from app.models import ATSProvider
from app.scrapers import extract, http
from app.scrapers.base import BaseScraper, CompanyRef, NormalizedJob, register

logger = logging.getLogger(__name__)

_BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


@register
class GreenhouseScraper(BaseScraper):
    provider = ATSProvider.greenhouse

    async def fetch_jobs(self, company: CompanyRef) -> list[NormalizedJob]:
        url = _BOARD_URL.format(token=company.ats_identifier)
        resp = await http.get(url, params={"content": "true"})
        payload = resp.json()
        jobs_raw = payload.get("jobs", [])
        logger.info(
            "greenhouse: %s (%s) → %d postings",
            company.name, company.ats_identifier, len(jobs_raw),
        )

        results: list[NormalizedJob] = []
        for j in jobs_raw:
            description = extract.html_to_text(j.get("content"))
            location_raw = (j.get("location") or {}).get("name")
            posted_at = extract.parse_iso_datetime(
                j.get("first_published")
            ) or extract.parse_iso_datetime(j.get("updated_at"))
            min_exp, max_exp = extract.extract_experience(description)

            results.append(
                NormalizedJob(
                    external_id=str(j["id"]),
                    title=j["title"],
                    apply_url=j["absolute_url"],
                    company_name=company.name,
                    location_raw=location_raw,
                    location_type=extract.classify_location(location_raw),
                    original_posted_at=posted_at,
                    description=description,
                    skills=extract.extract_skills(description),
                    min_experience=min_exp,
                    max_experience=max_exp,
                )
            )
        return results
