"""Workday scraper.

Workday's public "CXS" JSON API serves the same data the career site renders —
no browser needed:
    POST https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
Body: {"appliedFacets":{}, "limit":20, "offset":N, "searchText":""}
Returns {total, jobPostings:[{title, externalPath, locationsText, postedOn,
bulletFields}]}.

`ats_identifier` encodes the tenant coordinates as "tenant:datacenter:site",
e.g. "nvidia:wd5:NVIDIAExternalCareerSite".

Caveat: the listing only exposes `postedOn` as relative text ("Posted Today",
"Posted 3 Days Ago"), so posting dates are day-granular approximations. Exact
dates would require a per-job detail fetch (fetch_detail hook, Phase 3).
"""
from __future__ import annotations

import logging

from app.models import ATSProvider
from app.scrapers import extract, http
from app.scrapers.base import BaseScraper, CompanyRef, NormalizedJob, register

logger = logging.getLogger(__name__)

_PAGE_SIZE = 20  # Workday caps the CXS endpoint at 20 per request
_MAX_PAGES = 50  # safety cap (→ 1000 jobs); logged if hit


def _parse_identifier(identifier: str) -> tuple[str, str, str]:
    parts = identifier.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"workday ats_identifier must be 'tenant:datacenter:site', got {identifier!r}"
        )
    return parts[0], parts[1], parts[2]


@register
class WorkdayScraper(BaseScraper):
    provider = ATSProvider.workday

    async def fetch_jobs(self, company: CompanyRef) -> list[NormalizedJob]:
        tenant, dc, site = _parse_identifier(company.ats_identifier)
        base = f"https://{tenant}.{dc}.myworkdayjobs.com"
        api_url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
        apply_prefix = f"{base}/en-US/{site}"

        results: list[NormalizedJob] = []
        offset = 0
        for page in range(_MAX_PAGES):
            resp = await http.post(
                api_url,
                json={
                    "appliedFacets": {},
                    "limit": _PAGE_SIZE,
                    "offset": offset,
                    "searchText": "",
                },
            )
            payload = resp.json()
            postings = payload.get("jobPostings", [])
            if not postings:
                break
            for j in postings:
                external_path = j.get("externalPath") or ""
                location_raw = j.get("locationsText")
                results.append(
                    NormalizedJob(
                        # externalPath is stable & unique within a site.
                        external_id=external_path or str(j.get("bulletFields")),
                        title=j["title"],
                        apply_url=f"{apply_prefix}{external_path}",
                        company_name=company.name,
                        location_raw=location_raw,
                        location_type=extract.classify_location(location_raw),
                        original_posted_at=extract.parse_relative_posted(
                            j.get("postedOn")
                        ),
                    )
                )
            offset += _PAGE_SIZE
            if offset >= payload.get("total", 0):
                break
        else:
            logger.warning(
                "workday: %s hit page cap (%d) — coverage bounded to %d jobs",
                company.name, _MAX_PAGES, _MAX_PAGES * _PAGE_SIZE,
            )
        logger.info(
            "workday: %s (%s) → %d postings",
            company.name, company.ats_identifier, len(results),
        )
        return results
