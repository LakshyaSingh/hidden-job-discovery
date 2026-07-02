"""Lever scraper.

Lever exposes a public JSON postings API — no browser needed:
    https://api.lever.co/v0/postings/{site}?mode=json
Returns a flat array of postings. Each carries id, text (title), hostedUrl,
categories.{location,commitment,...}, workplaceType (remote/hybrid/on-site),
createdAt (epoch ms), and descriptionPlain.
"""
from __future__ import annotations

import logging

from app.models import ATSProvider
from app.scrapers import extract, http
from app.scrapers.base import BaseScraper, CompanyRef, NormalizedJob, register

logger = logging.getLogger(__name__)

_POSTINGS_URL = "https://api.lever.co/v0/postings/{site}"


@register
class LeverScraper(BaseScraper):
    provider = ATSProvider.lever

    async def fetch_jobs(self, company: CompanyRef) -> list[NormalizedJob]:
        url = _POSTINGS_URL.format(site=company.ats_identifier)
        resp = await http.get(url, params={"mode": "json"})
        postings = resp.json()  # Lever returns a top-level array
        logger.info(
            "lever: %s (%s) → %d postings",
            company.name, company.ats_identifier, len(postings),
        )

        results: list[NormalizedJob] = []
        for j in postings:
            categories = j.get("categories") or {}
            location_raw = categories.get("location")
            description = j.get("descriptionPlain") or extract.html_to_text(
                j.get("description")
            )
            min_exp, max_exp = extract.extract_experience(description)

            results.append(
                NormalizedJob(
                    external_id=str(j["id"]),
                    title=j["text"],
                    apply_url=j.get("hostedUrl") or j.get("applyUrl"),
                    company_name=company.name,
                    location_raw=location_raw,
                    location_type=extract.location_type_from_workplace(
                        j.get("workplaceType"), location_raw=location_raw
                    ),
                    original_posted_at=extract.parse_epoch_ms(j.get("createdAt")),
                    employment_type=categories.get("commitment"),
                    description=description,
                    skills=extract.extract_skills(description),
                    min_experience=min_exp,
                    max_experience=max_exp,
                )
            )
        return results
