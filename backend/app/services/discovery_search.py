"""Discover ATS board tokens via Google Programmable Search.

Uses the official Custom Search JSON API, not Google HTML scraping. Search
results point at public job-posting URLs; we extract the ATS board token from
the URL, then verify the board through the normal ATS API before registering it.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ATSProvider, Company
from app.services.discovery import (
    _prettify,
    _probe_ashby,
    _probe_greenhouse,
    _probe_lever,
)

logger = logging.getLogger(__name__)
settings = get_settings()

_GOOGLE_CSE_URL = "https://customsearch.googleapis.com/customsearch/v1"
_CONCURRENCY = 4
_TIMEOUT = 15.0
_RESULTS_PER_QUERY = 10

_PROVIDER_HOSTS: list[tuple[ATSProvider, str]] = [
    (ATSProvider.greenhouse, "job-boards.greenhouse.io"),
    (ATSProvider.greenhouse, "boards.greenhouse.io"),
    (ATSProvider.lever, "jobs.lever.co"),
    (ATSProvider.ashby, "jobs.ashbyhq.com"),
]

_DEFAULT_ROLES = [
    "product manager",
    "software engineer",
    "data scientist",
    "designer",
    "sales",
    "marketing",
    "customer success",
    "operations",
]

_BAD_TOKENS = {
    "embed",
    "job_app",
    "jobs",
    "postings",
}


@dataclass(frozen=True)
class SearchToken:
    provider: ATSProvider
    identifier: str
    url: str


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _token_from_url(url: str) -> SearchToken | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None

    first = parts[0]
    if first.lower() in _BAD_TOKENS:
        return None

    if host in {"job-boards.greenhouse.io", "boards.greenhouse.io"}:
        return SearchToken(ATSProvider.greenhouse, first.lower(), url)
    if host == "jobs.lever.co":
        return SearchToken(ATSProvider.lever, first.lower(), url)
    if host == "jobs.ashbyhq.com":
        return SearchToken(ATSProvider.ashby, first, url)
    return None


def extract_tokens(items: list[dict]) -> list[SearchToken]:
    seen: set[tuple[ATSProvider, str]] = set()
    tokens: list[SearchToken] = []
    for item in items:
        link = item.get("link")
        if not isinstance(link, str):
            continue
        token = _token_from_url(link)
        if token is None:
            continue
        key = (token.provider, token.identifier)
        if key in seen:
            continue
        seen.add(key)
        tokens.append(token)
    return tokens


def build_queries(roles: list[str] | None = None) -> list[tuple[ATSProvider, str, str]]:
    role_terms = roles or _DEFAULT_ROLES
    queries: list[tuple[ATSProvider, str, str]] = []
    for provider, host in _PROVIDER_HOSTS:
        for role in role_terms:
            queries.append((provider, host, f'site:{host} "{role}"'))
    return queries


async def fetch_search_tokens(
    *,
    roles: list[str] | None = None,
    max_queries: int | None = None,
) -> list[SearchToken]:
    """Run bounded Google CSE queries and return unique ATS board tokens."""
    if not settings.google_cse_key or not settings.google_cse_cx:
        logger.info("google discovery: missing credentials; skipping")
        return []

    limit = max_queries if max_queries is not None else settings.google_cse_max_queries
    queries = build_queries(roles)[:max(0, limit)]
    if not queries:
        return []

    sem = asyncio.Semaphore(_CONCURRENCY)
    tokens: list[SearchToken] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        async def run_query(provider: ATSProvider, host: str, query: str) -> list[SearchToken]:
            async with sem:
                resp = await client.get(
                    _GOOGLE_CSE_URL,
                    params={
                        "key": settings.google_cse_key,
                        "cx": settings.google_cse_cx,
                        "q": query,
                        "num": _RESULTS_PER_QUERY,
                        "gl": "us",
                        "cr": "countryUS",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(
                        "google discovery: query failed provider=%s host=%s status=%d",
                        provider.value,
                        host,
                        resp.status_code,
                    )
                    return []
                return [
                    token for token in extract_tokens(resp.json().get("items") or [])
                    if token.provider == provider
                ]

        batches = await asyncio.gather(*(run_query(*q) for q in queries))

    seen: set[tuple[ATSProvider, str]] = set()
    for batch in batches:
        for token in batch:
            key = (token.provider, token.identifier)
            if key in seen:
                continue
            seen.add(key)
            tokens.append(token)

    logger.info(
        "google discovery: queries=%d tokens=%d", len(queries), len(tokens)
    )
    return tokens


async def _probe_token(
    client: httpx.AsyncClient, provider: ATSProvider, identifier: str
) -> str | None:
    if provider == ATSProvider.greenhouse:
        return await _probe_greenhouse(client, identifier)
    if provider == ATSProvider.lever:
        return await _probe_lever(client, identifier)
    if provider == ATSProvider.ashby:
        return await _probe_ashby(client, identifier)
    return None


def _unique_slug(base: str, provider: ATSProvider, known_slugs: set[str]) -> str:
    slug = _slugify(base) or provider.value
    if slug not in known_slugs:
        return slug
    provider_slug = f"{slug}-{provider.value}"
    if provider_slug not in known_slugs:
        return provider_slug
    i = 2
    while f"{provider_slug}-{i}" in known_slugs:
        i += 1
    return f"{provider_slug}-{i}"


async def discover_from_search(
    session: AsyncSession,
    *,
    roles: list[str] | None = None,
    max_queries: int | None = None,
) -> dict:
    """Search Google for ATS job URLs, verify tokens, and register live boards."""
    tokens = await fetch_search_tokens(roles=roles, max_queries=max_queries)
    if not tokens:
        return {"queries": 0, "tokens": 0, "found": 0, "added": 0}

    existing = (
        await session.execute(
            select(Company.ats_provider, Company.ats_identifier, Company.slug)
        )
    ).all()
    known_boards = {(p, i) for p, i, _ in existing}
    known_slugs = {s for _, _, s in existing}

    found = added = 0
    sem = asyncio.Semaphore(_CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "hidden-job-discovery/1.0"},
    ) as client:
        async def work(token: SearchToken):
            async with sem:
                try:
                    hit = await _probe_token(client, token.provider, token.identifier)
                except Exception:  # noqa: BLE001 - a dead board is just a miss
                    hit = None
                return token, hit

        results = await asyncio.gather(*(work(token) for token in tokens))

    for token, identifier in results:
        if not identifier:
            continue
        found += 1
        if (token.provider, identifier) in known_boards:
            continue
        slug = _unique_slug(identifier, token.provider, known_slugs)
        session.add(
            Company(
                name=_prettify(identifier),
                slug=slug,
                ats_provider=token.provider,
                ats_identifier=identifier,
                careers_url=token.url,
                active=True,
            )
        )
        known_boards.add((token.provider, identifier))
        known_slugs.add(slug)
        added += 1

    await session.commit()
    stats = {
        "queries": min(
            max_queries if max_queries is not None else settings.google_cse_max_queries,
            len(build_queries(roles)),
        ),
        "tokens": len(tokens),
        "found": found,
        "added": added,
    }
    logger.info(
        "google discovery: tokens=%d found=%d added=%d",
        stats["tokens"],
        stats["found"],
        stats["added"],
    )
    return stats
