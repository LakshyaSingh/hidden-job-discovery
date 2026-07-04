"""The Muse aggregator source.

The Muse's public API (no key) lists ~400k jobs across thousands of real US
employers. We ingest a bounded slice into our own DB so search stays fast and
we respect the source. Each job carries its employer name; the aggregate
service maps that to a Company. US-only: non-US locations are skipped.

    GET https://www.themuse.com/api/public/jobs?page=N

Fields used: name, company.name, locations[].name, refs.landing_page,
publication_date, levels[].name, contents (HTML).
"""
from __future__ import annotations

import html
import logging

from bs4 import BeautifulSoup

from app.config import get_settings
from app.scrapers import extract, http
from app.scrapers.base import NormalizedJob

logger = logging.getLogger(__name__)
settings = get_settings()

_URL = "https://www.themuse.com/api/public/jobs"

# The Muse seniority buckets → (min, max) years, used when the description has
# no explicit number.
_LEVEL_EXP = {
    "internship": (0, 1),
    "entry level": (0, 2),
    "mid level": (2, 5),
    "senior level": (5, None),
    "management": (8, None),
}


def _html_to_text(raw: str | None) -> str | None:
    if not raw:
        return None
    return html.unescape(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)) or None


def _level_experience(levels: list[dict]) -> tuple[int | None, int | None]:
    for lv in levels:
        span = _LEVEL_EXP.get((lv.get("name") or "").lower())
        if span:
            return span
    return None, None


async def fetch_themuse(max_pages: int | None = None) -> list[NormalizedJob]:
    pages = max_pages if max_pages is not None else settings.themuse_max_pages
    results: list[NormalizedJob] = []
    for page in range(1, pages + 1):
        resp = await http.get(_URL, params={"page": page})
        if resp.status_code != 200:
            break
        payload = resp.json()
        for j in payload.get("results", []):
            company = (j.get("company") or {}).get("name")
            if not company:
                continue
            locations = [
                loc.get("name") for loc in (j.get("locations") or []) if loc.get("name")
            ]
            us_locs = [loc for loc in locations if extract.is_us_location(loc) is True]
            if not us_locs:  # US-only board
                continue
            location_raw = "; ".join(us_locs[:3])
            landing = (j.get("refs") or {}).get("landing_page")
            if not landing:
                continue
            description = _html_to_text(j.get("contents"))
            min_exp, max_exp = extract.extract_experience(description)
            if min_exp is None and max_exp is None:
                min_exp, max_exp = _level_experience(j.get("levels") or [])
            results.append(
                NormalizedJob(
                    external_id=str(j["id"]),
                    title=j.get("name") or "",
                    apply_url=landing,
                    company_name=company,
                    location_raw=location_raw,
                    location_type=extract.classify_location(location_raw),
                    is_us=True,
                    original_posted_at=extract.parse_iso_datetime(
                        j.get("publication_date")
                    ),
                    description=description,
                    skills=extract.extract_skills(description),
                    min_experience=min_exp,
                    max_experience=max_exp,
                )
            )
    logger.info("themuse: fetched %d US jobs across %d pages", len(results), pages)
    return results
