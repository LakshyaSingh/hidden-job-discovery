"""Company discovery.

There is no official "list every company on Greenhouse/Lever/Ashby" endpoint,
so we discover boards by probing: for each candidate slug we hit each ATS's
public API and register the company only when the board actually returns jobs.
Wrong guesses simply do not match, so bad data can't leak in.

Greenhouse, Lever, and Ashby use lowercase-name slugs (e.g. jobs.lever.co/spotify),
which makes candidate slugs easy to derive and gives good hit rates. Workday and
SmartRecruiters need tenant-specific identifiers that can't be guessed from a
name, so they're added manually, not discovered here.

Run via `python -m app.worker.run discover`. Newly-added companies are then
picked up by the normal crawl.
"""
from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ATSProvider, Company
from app.services.discovery_candidates import CANDIDATE_SLUGS

logger = logging.getLogger(__name__)

_CONCURRENCY = 8
_TIMEOUT = 12.0


async def _probe_greenhouse(client: httpx.AsyncClient, slug: str) -> str | None:
    r = await client.get(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    )
    if r.status_code == 200 and r.json().get("jobs"):
        return slug
    return None


async def _probe_lever(client: httpx.AsyncClient, slug: str) -> str | None:
    r = await client.get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list) and data:
            return slug
    return None


async def _probe_ashby(client: httpx.AsyncClient, slug: str) -> str | None:
    r = await client.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    )
    if r.status_code == 200 and r.json().get("jobs"):
        return slug
    return None


# Ordered: first provider with a live board wins.
_PROBERS: list[tuple[ATSProvider, "callable"]] = [
    (ATSProvider.greenhouse, _probe_greenhouse),
    (ATSProvider.lever, _probe_lever),
    (ATSProvider.ashby, _probe_ashby),
]


def _prettify(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("-", " ").split())


async def _discover_one(
    client: httpx.AsyncClient, slug: str
) -> tuple[ATSProvider, str] | None:
    for provider, prober in _PROBERS:
        try:
            hit = await prober(client, slug)
        except Exception:  # noqa: BLE001 — a dead host just means "no board"
            hit = None
        if hit:
            return provider, hit
    return None


async def discover_companies(
    session: AsyncSession, candidates: list[str] | None = None
) -> dict:
    """Probe candidate slugs, register any live boards not already tracked.
    Returns {"probed", "found", "added"}."""
    slugs = candidates if candidates is not None else CANDIDATE_SLUGS

    # What we already have, to skip re-adding.
    existing = (
        await session.execute(
            select(Company.ats_provider, Company.ats_identifier, Company.slug)
        )
    ).all()
    known_boards = {(p, i) for p, i, _ in existing}
    known_slugs = {s for _, _, s in existing}

    sem = asyncio.Semaphore(_CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True,
        headers={"User-Agent": "hidden-job-discovery/1.0"},
    ) as client:
        async def work(slug: str):
            async with sem:
                return slug, await _discover_one(client, slug)

        results = await asyncio.gather(*(work(s) for s in slugs))

    found = added = 0
    for slug, hit in results:
        if not hit:
            continue
        found += 1
        provider, identifier = hit
        if (provider, identifier) in known_boards or slug in known_slugs:
            continue
        session.add(
            Company(
                name=_prettify(slug),
                slug=slug,
                ats_provider=provider,
                ats_identifier=identifier,
                active=True,
            )
        )
        known_boards.add((provider, identifier))
        known_slugs.add(slug)
        added += 1

    await session.commit()
    stats = {"probed": len(slugs), "found": found, "added": added}
    logger.info(
        "discovery: probed=%d found=%d added=%d", stats["probed"],
        stats["found"], stats["added"],
    )
    return stats
