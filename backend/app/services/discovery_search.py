"""Discover ATS board tokens via Brave Search.

Search results point at public job-posting URLs; we extract the ATS board token
from the URL, then verify the board through the normal ATS API before registering it.
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
    _probe_smartrecruiters,
    _probe_workday,
)

logger = logging.getLogger(__name__)
settings = get_settings()

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_CONCURRENCY = 4
_TIMEOUT = 15.0
_RESULTS_PER_QUERY = 10

_PROVIDER_HOSTS: list[tuple[ATSProvider, str]] = [
    (ATSProvider.greenhouse, "job-boards.greenhouse.io"),
    (ATSProvider.greenhouse, "boards.greenhouse.io"),
    (ATSProvider.lever, "jobs.lever.co"),
    (ATSProvider.ashby, "jobs.ashbyhq.com"),
    (ATSProvider.smartrecruiters, "jobs.smartrecruiters.com"),
    # Search is the only way a Workday board is ever found: its identifier is
    # a tenant/datacenter/site triple that appears nowhere in a company name,
    # so it cannot be guessed the way a board token can. A posting URL carries
    # all three. Every tenant is its own subdomain, so the query targets the
    # apex domain and the parser picks the tenant out of the host.
    (ATSProvider.workday, "myworkdayjobs.com"),
]

# {tenant}.{wdN}.myworkdayjobs.com
_WORKDAY_HOST_RE = re.compile(r"^([a-z0-9][a-z0-9-]*)\.(wd\d+)\.myworkdayjobs\.com$")
# A leading path segment like "en-US" or "fr", which precedes the site name.
_LOCALE_RE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$", re.I)

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
    # Workday and SmartRecruiters path noise that is never a site or company.
    "job",
    "details",
    "search",
    "oneclick-ui",
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
    # Keep the URL's casing: the API accepts either, but the canonical form
    # is what the apply links use.
    if host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"}:
        return SearchToken(ATSProvider.smartrecruiters, first, url)

    workday = _WORKDAY_HOST_RE.match(host)
    if workday:
        tenant, datacenter = workday.groups()
        # .../en-US/CareerSite/job/... — the locale is optional, the site is
        # whatever follows it.
        segments = parts[1:] if _LOCALE_RE.match(first) else parts
        if not segments:
            return None
        site = segments[0]
        if site.lower() in _BAD_TOKENS:
            return None
        return SearchToken(
            ATSProvider.workday, f"{tenant}:{datacenter}:{site}", url
        )
    return None


def extract_tokens(items: list[dict]) -> list[SearchToken]:
    seen: set[tuple[ATSProvider, str]] = set()
    tokens: list[SearchToken] = []
    for item in items:
        link = item.get("url") or item.get("link")
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
    """One query per (host, role), ordered role-major.

    The caller truncates this list to the query budget, so the ordering is
    load-bearing: grouping by host meant the budget was spent entirely on
    Greenhouse and Lever, and the hosts further down were never searched at
    all. Interleaving gives every provider a share of whatever budget exists.
    """
    role_terms = roles or _DEFAULT_ROLES
    queries: list[tuple[ATSProvider, str, str]] = []
    for role in role_terms:
        for provider, host in _PROVIDER_HOSTS:
            queries.append((provider, host, f'site:{host} "{role}"'))
    return queries


async def fetch_search_tokens(
    *,
    roles: list[str] | None = None,
    max_queries: int | None = None,
) -> list[SearchToken]:
    """Run bounded Brave Search queries and return unique ATS board tokens."""
    if not settings.brave_search_api_key:
        logger.info("brave discovery: missing credentials; skipping")
        return []

    limit = max_queries if max_queries is not None else settings.brave_search_max_queries
    queries = build_queries(roles)[:max(0, limit)]
    if not queries:
        return []

    sem = asyncio.Semaphore(_CONCURRENCY)
    tokens: list[SearchToken] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        async def run_query(provider: ATSProvider, host: str, query: str) -> list[SearchToken]:
            async with sem:
                resp = await client.get(
                    _BRAVE_SEARCH_URL,
                    params={
                        "q": query,
                        "count": _RESULTS_PER_QUERY,
                        "country": "US",
                        "search_lang": "en",
                    },
                    headers={"X-Subscription-Token": settings.brave_search_api_key},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "brave discovery: query failed provider=%s host=%s status=%d",
                        provider.value,
                        host,
                        resp.status_code,
                    )
                    return []
                return [
                    token for token in extract_tokens(
                        resp.json().get("web", {}).get("results") or []
                    )
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
        "brave discovery: queries=%d tokens=%d", len(queries), len(tokens)
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
    if provider == ATSProvider.smartrecruiters:
        return await _probe_smartrecruiters(client, identifier)
    if provider == ATSProvider.workday:
        return await _probe_workday(client, identifier)
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

    # Read the existing boards only after the probing. Querying up front holds
    # a connection open across every verification request above, and a managed
    # Postgres drops it as idle long before that finishes.
    existing = (
        await session.execute(
            select(Company.ats_provider, Company.ats_identifier, Company.slug)
        )
    ).all()
    known_boards = {(p, i) for p, i, _ in existing}
    known_slugs = {s for _, _, s in existing}

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
            max_queries if max_queries is not None else settings.brave_search_max_queries,
            len(build_queries(roles)),
        ),
        "tokens": len(tokens),
        "found": found,
        "added": added,
    }
    logger.info(
        "brave discovery: tokens=%d found=%d added=%d",
        stats["tokens"],
        stats["found"],
        stats["added"],
    )
    return stats
