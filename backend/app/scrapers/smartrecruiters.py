"""SmartRecruiters scraper.

SmartRecruiters exposes a public postings API — no browser needed:
    https://api.smartrecruiters.com/v1/companies/{company}/postings
Returns {content: [...], totalFound, limit, offset} and paginates. Each posting
carries id, name (title), releasedDate (ISO), location {city,region,remote,hybrid,
fullLocation}, experienceLevel {label}, typeOfEmployment {label}.
"""
from __future__ import annotations

import logging

from app.models import ATSProvider, LocationType
from app.scrapers import extract, http
from app.scrapers.base import BaseScraper, CompanyRef, NormalizedJob, register

logger = logging.getLogger(__name__)

_POSTINGS_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
_APPLY_URL = "https://jobs.smartrecruiters.com/{company}/{posting_id}"
_PAGE_SIZE = 100
_MAX_PAGES = 50  # safety cap; logged if hit so coverage is never silently bounded


def _location(loc: dict) -> tuple[str | None, LocationType]:
    if not loc:
        return None, LocationType.unknown
    raw = loc.get("fullLocation") or ", ".join(
        p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p
    )
    if loc.get("remote"):
        return raw or "Remote", LocationType.remote
    if loc.get("hybrid"):
        return raw, LocationType.hybrid
    return raw or None, extract.classify_location(raw)


@register
class SmartRecruitersScraper(BaseScraper):
    provider = ATSProvider.smartrecruiters

    async def fetch_jobs(self, company: CompanyRef) -> list[NormalizedJob]:
        url = _POSTINGS_URL.format(company=company.ats_identifier)
        results: list[NormalizedJob] = []
        offset = 0
        for page in range(_MAX_PAGES):
            resp = await http.get(
                url, params={"limit": _PAGE_SIZE, "offset": offset}
            )
            payload = resp.json()
            postings = payload.get("content", [])
            if not postings:
                break
            for j in postings:
                location_raw, location_type = _location(j.get("location") or {})
                emp = (j.get("typeOfEmployment") or {}).get("label")
                results.append(
                    NormalizedJob(
                        external_id=str(j["id"]),
                        title=j["name"],
                        apply_url=_APPLY_URL.format(
                            company=company.ats_identifier, posting_id=j["id"]
                        ),
                        company_name=company.name,
                        location_raw=location_raw,
                        location_type=location_type,
                        original_posted_at=extract.parse_iso_datetime(
                            j.get("releasedDate")
                        ),
                        employment_type=emp,
                    )
                )
            offset += _PAGE_SIZE
            if offset >= payload.get("totalFound", 0):
                break
        else:
            logger.warning(
                "smartrecruiters: %s hit page cap (%d) — coverage bounded",
                company.name, _MAX_PAGES,
            )
        logger.info(
            "smartrecruiters: %s (%s) → %d postings",
            company.name, company.ats_identifier, len(results),
        )
        return results
