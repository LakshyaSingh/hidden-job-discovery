"""Ashby scraper.

Ashby exposes a public job-board posting API — no browser needed:
    https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true
Returns {"jobs": [...]}. Each job carries id, title, location, workplaceType,
isRemote, publishedAt (ISO-8601), employmentType, jobUrl/applyUrl,
descriptionPlain/descriptionHtml, and (opt-in) compensation.
"""
from __future__ import annotations

import logging

from app.models import ATSProvider
from app.scrapers import extract, http
from app.scrapers.base import BaseScraper, CompanyRef, NormalizedJob, register

logger = logging.getLogger(__name__)

_BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{name}"


@register
class AshbyScraper(BaseScraper):
    provider = ATSProvider.ashby

    async def fetch_jobs(self, company: CompanyRef) -> list[NormalizedJob]:
        url = _BOARD_URL.format(name=company.ats_identifier)
        resp = await http.get(url, params={"includeCompensation": "true"})
        jobs_raw = resp.json().get("jobs", [])
        logger.info(
            "ashby: %s (%s) → %d postings",
            company.name, company.ats_identifier, len(jobs_raw),
        )

        results: list[NormalizedJob] = []
        for j in jobs_raw:
            # Only surface listed postings (Ashby hides unlisted ones from boards).
            if j.get("isListed") is False:
                continue
            location_raw = j.get("location")
            description = j.get("descriptionPlain") or extract.html_to_text(
                j.get("descriptionHtml")
            )
            min_exp, max_exp = extract.extract_experience(description)

            comp = j.get("compensation") or {}
            summary = comp.get("scrapeableCompensationSalarySummary") or comp.get(
                "compensationTierSummary"
            )
            salary_min, salary_max, currency = extract.parse_salary_summary(summary)

            results.append(
                NormalizedJob(
                    external_id=str(j["id"]),
                    title=j["title"],
                    apply_url=j.get("applyUrl") or j.get("jobUrl"),
                    company_name=company.name,
                    location_raw=location_raw,
                    location_type=extract.location_type_from_workplace(
                        j.get("workplaceType"),
                        is_remote=j.get("isRemote"),
                        location_raw=location_raw,
                    ),
                    original_posted_at=extract.parse_iso_datetime(j.get("publishedAt")),
                    employment_type=j.get("employmentType"),
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=currency,
                    description=description,
                    skills=extract.extract_skills(description),
                    min_experience=min_exp,
                    max_experience=max_exp,
                )
            )
        return results
