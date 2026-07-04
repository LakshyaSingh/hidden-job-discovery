"""Workday scraper.

Workday's public "CXS" JSON API serves the same data the career site renders,
no browser needed. Two endpoints are used:

    POST {base}/wday/cxs/{tenant}/{site}/jobs      -> listing (paged, 20/page)
    GET  {base}/wday/cxs/{tenant}/{site}{path}     -> one job's full detail

The listing only exposes `locationsText` as a summary ("3 Locations") and a
relative `postedOn` ("Posted 3 Days Ago"), which is why we fetch each job's
detail: it returns the real `location` + `additionalLocations`, an exact
`startDate`, `timeType`, and the full `jobDescription` (so we can extract
experience and skills). Detail fetching is capped by `workday_max_jobs` and
rate-limited by the shared HTTP client.

`ats_identifier` encodes the tenant coordinates as "tenant:datacenter:site",
e.g. "nvidia:wd5:NVIDIAExternalCareerSite".
"""
from __future__ import annotations

import html
import logging

from bs4 import BeautifulSoup

from app.config import get_settings
from app.models import ATSProvider
from app.scrapers import extract, http
from app.scrapers.base import BaseScraper, CompanyRef, NormalizedJob, register

logger = logging.getLogger(__name__)
settings = get_settings()

_PAGE_SIZE = 20  # Workday caps the CXS endpoint at 20 per request


def _parse_identifier(identifier: str) -> tuple[str, str, str]:
    parts = identifier.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"workday ats_identifier must be 'tenant:datacenter:site', got {identifier!r}"
        )
    return parts[0], parts[1], parts[2]


def _pretty_location(loc: str) -> str:
    """Reformat Workday's "Country, Region, City" into a familiar "City, Region"
    (US) or "City, Country" form."""
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if not parts:
        return loc
    if parts[0] == "US" and len(parts) >= 3:
        return f"{parts[-1]}, {parts[1]}"  # City, ST
    if len(parts) >= 2:
        return f"{parts[-1]}, {parts[0]}"  # City, Country
    return parts[0]


def _slug_is_us(external_path: str) -> bool | None:
    """Fallback US check from the externalPath location slug, which begins with
    the country ("/job/US-CA-Santa-Clara/..." vs "/job/Taiwan-Taipei/...")."""
    if "/job/" not in external_path:
        return None
    slug = external_path.split("/job/", 1)[1].split("/", 1)[0]
    if not slug:
        return None
    return slug.upper().startswith("US-") or slug.upper() == "US"


def _html_to_text(raw: str | None) -> str | None:
    if not raw:
        return None
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return html.unescape(text) or None


@register
class WorkdayScraper(BaseScraper):
    provider = ATSProvider.workday

    async def fetch_jobs(self, company: CompanyRef) -> list[NormalizedJob]:
        tenant, dc, site = _parse_identifier(company.ats_identifier)
        base = f"https://{tenant}.{dc}.myworkdayjobs.com"
        api_url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
        cxs_prefix = f"{base}/wday/cxs/{tenant}/{site}"
        apply_prefix = f"{base}/en-US/{site}"
        cap = settings.workday_max_jobs

        # 1) Page the listing until we have `cap` postings (or run out).
        raw: list[dict] = []
        offset = 0
        total = None
        while len(raw) < cap:
            resp = await http.post(
                api_url,
                json={"appliedFacets": {}, "limit": _PAGE_SIZE,
                      "offset": offset, "searchText": ""},
            )
            payload = resp.json()
            total = payload.get("total", 0)
            postings = payload.get("jobPostings", [])
            if not postings:
                break
            raw.extend(postings)
            offset += _PAGE_SIZE
            if offset >= total:
                break
        if total and total > cap:
            logger.info(
                "workday: %s has %d jobs; capped to %d (workday_max_jobs)",
                company.name, total, cap,
            )

        # 2) Enrich each posting with its detail record.
        results: list[NormalizedJob] = []
        for j in raw[:cap]:
            external_path = j.get("externalPath") or ""
            external_id = external_path or str(j.get("bulletFields"))
            try:
                detail = (await http.get(f"{cxs_prefix}{external_path}")).json()
                info = detail.get("jobPostingInfo", {})
            except Exception:  # noqa: BLE001 — fall back to listing-only data
                logger.warning("workday: detail fetch failed for %s", external_path)
                info = {}

            locations = [
                loc for loc in [info.get("location"), *info.get("additionalLocations", [])]
                if loc
            ]
            if locations:
                pretty = [_pretty_location(loc) for loc in locations]
                location_raw = "; ".join(pretty[:4])
                if len(pretty) > 4:
                    location_raw += f" (+{len(pretty) - 4} more)"
                is_us = any(
                    loc.strip().upper().startswith("US,") or "united states" in loc.lower()
                    for loc in locations
                )
            else:
                location_raw = j.get("locationsText")
                is_us = _slug_is_us(external_path)

            description = _html_to_text(info.get("jobDescription"))
            min_exp, max_exp = extract.extract_experience(description)
            posted_at = (
                extract.parse_iso_datetime(info.get("startDate"))
                or extract.parse_relative_posted(j.get("postedOn"))
            )

            results.append(
                NormalizedJob(
                    external_id=external_id,
                    title=info.get("title") or j["title"],
                    apply_url=f"{apply_prefix}{external_path}",
                    company_name=company.name,
                    location_raw=location_raw,
                    location_type=extract.classify_location(location_raw),
                    is_us=is_us,
                    original_posted_at=posted_at,
                    employment_type=info.get("timeType"),
                    description=description,
                    skills=extract.extract_skills(description),
                    min_experience=min_exp,
                    max_experience=max_exp,
                )
            )

        logger.info(
            "workday: %s (%s) → %d postings",
            company.name, company.ats_identifier, len(results),
        )
        return results
