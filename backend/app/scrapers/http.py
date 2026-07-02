"""Shared async HTTP client with per-host rate limiting and retry/backoff.

All scrapers should fetch through `get(...)` so politeness and resilience are
uniform. Per-domain token spacing satisfies the "respect site rate limits"
requirement without a shared external service.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from urllib.parse import urlparse

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_last_request_at: dict[str, float] = defaultdict(float)
_host_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

_USER_AGENT = "HiddenJobDiscovery/0.1 (+https://example.com/bot)"


async def _throttle(host: str) -> None:
    """Ensure at least request_min_interval_seconds between hits to one host."""
    async with _host_locks[host]:
        elapsed = time.monotonic() - _last_request_at[host]
        wait = settings.request_min_interval_seconds - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at[host] = time.monotonic()


async def _request(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
) -> httpx.Response:
    """Throttled request with timeout and exponential-backoff retries."""
    host = urlparse(url).netloc
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    last_exc: Exception | None = None

    for attempt in range(settings.request_max_retries):
        await _throttle(host)
        try:
            async with httpx.AsyncClient(
                timeout=settings.request_timeout_seconds, follow_redirects=True
            ) as client:
                resp = await client.request(
                    method, url, params=params, json=json, headers=headers
                )
            # Retry transient server / rate-limit responses; raise on other 4xx.
            if resp.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"transient {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            backoff = 2**attempt
            logger.warning(
                "%s %s failed (attempt %d/%d): %s — retrying in %ss",
                method, url, attempt + 1, settings.request_max_retries, exc, backoff,
            )
            await asyncio.sleep(backoff)

    assert last_exc is not None
    raise last_exc


async def get(url: str, *, params: dict | None = None) -> httpx.Response:
    """GET with throttling, timeout, and exponential-backoff retries."""
    return await _request("GET", url, params=params)


async def post(url: str, *, json: dict | None = None) -> httpx.Response:
    """POST (JSON body) with throttling, timeout, and retries."""
    return await _request("POST", url, json=json)
