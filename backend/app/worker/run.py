"""CLI worker: seed sample companies and run crawls.

Usage:
    python -m app.worker.run seed      # insert a few real Greenhouse boards
    python -m app.worker.run discover  # probe candidate slugs, add live boards
    python -m app.worker.run crawl     # crawl all active companies once
    python -m app.worker.run loop 900  # crawl every 900s (Phase-1 scheduler)
"""
from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models import ATSProvider, Company
from app.services.crawl import crawl_all
from app.services.discovery import discover_companies

logger = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# A few well-known public ATS boards across providers for the proof of concept.
# (name, slug, provider, ats_identifier, careers_url)
SAMPLE_COMPANIES = [
    ("Stripe", "stripe", ATSProvider.greenhouse, "stripe", "https://stripe.com/jobs"),
    ("Databricks", "databricks", ATSProvider.greenhouse, "databricks",
     "https://databricks.com/company/careers"),
    ("Spotify", "spotify", ATSProvider.lever, "spotify",
     "https://www.lifeatspotify.com/jobs"),
    ("Ramp", "ramp", ATSProvider.ashby, "ramp", "https://ramp.com/careers"),
    ("Visa", "visa", ATSProvider.smartrecruiters, "Visa",
     "https://corporate.visa.com/en/jobs.html"),
    ("NVIDIA", "nvidia", ATSProvider.workday, "nvidia:wd5:NVIDIAExternalCareerSite",
     "https://www.nvidia.com/en-us/about-nvidia/careers/"),
]


async def init_db() -> None:
    # Dev convenience only; in production tables come from `alembic upgrade head`.
    if get_settings().auto_create_tables:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def seed() -> None:
    await init_db()
    async with SessionLocal() as session:
        for name, slug, provider, token, careers in SAMPLE_COMPANIES:
            exists = (
                await session.execute(select(Company).where(Company.slug == slug))
            ).scalar_one_or_none()
            if exists:
                continue
            session.add(
                Company(
                    name=name, slug=slug,
                    ats_provider=provider,
                    ats_identifier=token, careers_url=careers,
                )
            )
        try:
            await session.commit()
            logger.info("seeded %d sample companies", len(SAMPLE_COMPANIES))
        except IntegrityError:
            await session.rollback()


async def crawl_once() -> None:
    await init_db()
    async with SessionLocal() as session:
        runs = await crawl_all(session)
        total_new = sum(r.jobs_new for r in runs)
        logger.info("crawl complete: %d runs, %d new jobs", len(runs), total_new)


async def crawl_loop(interval: int) -> None:
    while True:
        await crawl_once()
        logger.info("sleeping %ss until next crawl", interval)
        await asyncio.sleep(interval)


async def discover_once() -> None:
    await init_db()
    async with SessionLocal() as session:
        stats = await discover_companies(session)
        logger.info(
            "discovery complete: probed=%d found=%d added=%d",
            stats["probed"], stats["found"], stats["added"],
        )


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "crawl"
    if cmd == "seed":
        asyncio.run(seed())
    elif cmd == "crawl":
        asyncio.run(crawl_once())
    elif cmd == "discover":
        asyncio.run(discover_once())
    elif cmd == "loop":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 900
        asyncio.run(crawl_loop(interval))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
