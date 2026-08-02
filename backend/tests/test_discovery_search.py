"""Tests for Brave Search-based ATS token discovery (network mocked)."""
import pytest
from sqlalchemy import select

from app.models import ATSProvider, Company
from app.services import discovery_search
from app.services.discovery_search import (
    SearchToken,
    build_queries,
    discover_from_search,
    extract_tokens,
    fetch_search_tokens,
)


def test_extract_tokens_from_ats_urls():
    tokens = extract_tokens(
        [
            {
                "link": "https://job-boards.greenhouse.io/acme/jobs/123",
            },
            {
                "link": "https://boards.greenhouse.io/acme/jobs/456",
            },
            {
                "link": "https://jobs.lever.co/globex/abc",
            },
            {
                "link": "https://jobs.ashbyhq.com/AcmeAI/abc",
            },
            {
                "link": "https://example.com/not-a-board",
            },
        ]
    )

    assert tokens == [
        SearchToken(ATSProvider.greenhouse, "acme", "https://job-boards.greenhouse.io/acme/jobs/123"),
        SearchToken(ATSProvider.lever, "globex", "https://jobs.lever.co/globex/abc"),
        SearchToken(ATSProvider.ashby, "AcmeAI", "https://jobs.ashbyhq.com/AcmeAI/abc"),
    ]


def test_build_queries_covers_supported_hosts():
    queries = build_queries(["product manager"])

    assert queries == [
        (ATSProvider.greenhouse, "job-boards.greenhouse.io", 'site:job-boards.greenhouse.io "product manager"'),
        (ATSProvider.greenhouse, "boards.greenhouse.io", 'site:boards.greenhouse.io "product manager"'),
        (ATSProvider.lever, "jobs.lever.co", 'site:jobs.lever.co "product manager"'),
        (ATSProvider.ashby, "jobs.ashbyhq.com", 'site:jobs.ashbyhq.com "product manager"'),
        (ATSProvider.smartrecruiters, "jobs.smartrecruiters.com", 'site:jobs.smartrecruiters.com "product manager"'),
        (ATSProvider.workday, "myworkdayjobs.com", 'site:myworkdayjobs.com "product manager"'),
    ]


def test_queries_are_role_major_so_truncation_does_not_starve_a_provider():
    """The caller slices this list to the query budget.

    Grouping by host meant a budget smaller than hosts x roles was spent
    entirely on the first providers, and SmartRecruiters and Workday were
    never searched at all.
    """
    queries = build_queries(["product manager", "software engineer"])
    hosts_in_budget = {host for _, host, _ in queries[: len(discovery_search._PROVIDER_HOSTS)]}

    assert hosts_in_budget == {host for _, host in discovery_search._PROVIDER_HOSTS}


def test_extract_tokens_from_workday_and_smartrecruiters_urls():
    """Neither identifier is guessable from a company name, so the URL is the
    only source: SmartRecruiters is case-sensitive, and Workday needs a
    tenant/datacenter/site triple."""
    tokens = extract_tokens(
        [
            {"link": "https://jobs.smartrecruiters.com/Visa/744000012345-analyst"},
            {"link": "https://careers.smartrecruiters.com/Bosch"},
            {
                "link": "https://nvidia.wd5.myworkdayjobs.com/en-US/"
                        "NVIDIAExternalCareerSite/job/US-CA/Engineer_JR1"
            },
            # No locale segment, and a three-digit datacenter.
            {"link": "https://acme.wd103.myworkdayjobs.com/CareerSite/job/x"},
            # Path noise rather than a site name.
            {"link": "https://acme.wd1.myworkdayjobs.com/en-US/job/details"},
            # Workday's own marketing site is not a tenant.
            {"link": "https://www.myworkdayjobs.com/about"},
        ]
    )

    assert [(t.provider, t.identifier) for t in tokens] == [
        (ATSProvider.smartrecruiters, "Visa"),
        (ATSProvider.smartrecruiters, "Bosch"),
        (ATSProvider.workday, "nvidia:wd5:NVIDIAExternalCareerSite"),
        (ATSProvider.workday, "acme:wd103:CareerSite"),
    ]


@pytest.mark.asyncio
async def test_fetch_search_tokens_skips_without_credentials(monkeypatch):
    monkeypatch.setattr(discovery_search.settings, "brave_search_api_key", "")

    assert await fetch_search_tokens(max_queries=1) == []


@pytest.mark.asyncio
async def test_fetch_search_tokens_uses_brave_search_api(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "web": {"results": [
                    {"url": "https://jobs.lever.co/acme/abc"},
                    {"url": "https://jobs.lever.co/acme/duplicate"},
                ]}
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, *, params, headers):
            self.calls.append((url, params, headers))
            return FakeResponse()

    fake_client = FakeClient()

    def fake_client_factory(*args, **kwargs):
        return fake_client

    monkeypatch.setattr(discovery_search.settings, "brave_search_api_key", "key")
    monkeypatch.setattr(discovery_search.httpx, "AsyncClient", fake_client_factory)

    tokens = await fetch_search_tokens(roles=["software engineer"], max_queries=3)

    assert tokens == [SearchToken(ATSProvider.lever, "acme", "https://jobs.lever.co/acme/abc")]
    assert len(fake_client.calls) == 3
    url, params, headers = fake_client.calls[0]
    assert url == "https://api.search.brave.com/res/v1/web/search"
    assert headers == {"X-Subscription-Token": "key"}
    assert params["count"] == 10
    assert params["country"] == "US"
    assert "site:" in params["q"]


@pytest.mark.asyncio
async def test_discover_from_search_registers_verified_tokens(session, monkeypatch):
    async def fake_fetch_search_tokens(*, roles=None, max_queries=None):
        return [
            SearchToken(ATSProvider.lever, "acme", "https://jobs.lever.co/acme/abc"),
            SearchToken(ATSProvider.ashby, "AcmeAI", "https://jobs.ashbyhq.com/AcmeAI/abc"),
        ]

    async def fake_probe_token(client, provider, identifier):
        return identifier if provider in {ATSProvider.lever, ATSProvider.ashby} else None

    monkeypatch.setattr(discovery_search, "fetch_search_tokens", fake_fetch_search_tokens)
    monkeypatch.setattr(discovery_search, "_probe_token", fake_probe_token)

    stats = await discover_from_search(session, roles=["product manager"], max_queries=1)

    assert stats["tokens"] == 2
    assert stats["found"] == 2
    assert stats["added"] == 2

    rows = (await session.execute(select(Company))).scalars().all()
    assert {(c.ats_provider, c.ats_identifier) for c in rows} == {
        (ATSProvider.lever, "acme"),
        (ATSProvider.ashby, "AcmeAI"),
    }

    stats2 = await discover_from_search(session, roles=["product manager"], max_queries=1)
    assert stats2["added"] == 0
