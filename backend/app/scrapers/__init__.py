"""Scraper package. Importing a provider module registers it via @register.

To add a provider: create app/scrapers/<name>.py subclassing BaseScraper with
`provider = ATSProvider.<name>` and the @register decorator, then import it here.
"""
from app.scrapers import ashby  # noqa: F401  (registers AshbyScraper)
from app.scrapers import greenhouse  # noqa: F401  (registers GreenhouseScraper)
from app.scrapers import lever  # noqa: F401  (registers LeverScraper)
from app.scrapers import smartrecruiters  # noqa: F401  (registers SmartRecruitersScraper)
from app.scrapers import workday  # noqa: F401  (registers WorkdayScraper)

__all__ = ["ashby", "greenhouse", "lever", "smartrecruiters", "workday"]
