"""Tests for company discovery (network mocked)."""
import pytest
from sqlalchemy import select

from app.models import ATSProvider, Company
from app.services import discovery
from app.services.discovery import _prettify, discover_companies
from app.services.discovery_candidates import CANDIDATE_SLUGS


def test_candidate_list_is_clean():
    assert len(CANDIDATE_SLUGS) == len(set(CANDIDATE_SLUGS))  # no dupes
    for s in CANDIDATE_SLUGS:
        assert s and s == s.strip().lower()
        assert "<" not in s and " " not in s  # no stray placeholders


def test_prettify():
    assert _prettify("moderntreasury") == "Moderntreasury"
    assert _prettify("weights-and-biases") == "Weights And Biases"


@pytest.mark.asyncio
async def test_discover_registers_and_dedupes(session, monkeypatch):
    # Pretend "acme" is a live Greenhouse board and "ghost" matches nothing.
    async def fake_discover_one(client, slug):
        return (ATSProvider.greenhouse, slug) if slug == "acme" else None

    monkeypatch.setattr(discovery, "_discover_one", fake_discover_one)

    stats = await discover_companies(session, candidates=["acme", "ghost"])
    assert stats == {"probed": 2, "found": 1, "added": 1}

    rows = (await session.execute(select(Company))).scalars().all()
    assert [c.slug for c in rows] == ["acme"]
    assert rows[0].ats_provider == ATSProvider.greenhouse

    # Running again must not create a duplicate.
    stats2 = await discover_companies(session, candidates=["acme"])
    assert stats2["added"] == 0
    count = len((await session.execute(select(Company))).scalars().all())
    assert count == 1
