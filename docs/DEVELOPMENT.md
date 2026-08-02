# Running it locally

Moved out of the README so that page can stay about what the project is. For the
design rationale behind any of this, see [ARCHITECTURE.md](../ARCHITECTURE.md).

```
backend/    FastAPI + SQLAlchemy + Alembic — scrapers, aggregators, ingest, worker
frontend/   Next.js + TypeScript dashboard
```

## Backend

Python 3.12 is what CI uses. Note that `pydantic-core` has no wheel for 3.14 yet,
so a newer system Python will fail to install; if that is what you have, pin the
version explicitly (`uv venv --python 3.12`, or pyenv).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

The quickest setup needs no Postgres at all. In `.env`:

```
DATABASE_URL=sqlite+aiosqlite:///./dev.db
AUTO_CREATE_TABLES=true
```

For Postgres instead, `docker compose up -d db` then `alembic upgrade head`.
`AUTO_CREATE_TABLES` must stay `false` anywhere real — production schema comes
from Alembic.

```bash
uvicorn app.main:app --reload    # API on :8000, OpenAPI at /docs
pytest                           # full suite
```

## Filling the database

Nothing appears until something has been crawled. The worker CLI is the only way
to run a crawl outside the API:

```bash
python -m app.worker.run seed             # a handful of known-good boards
python -m app.worker.run crawl            # crawl every active company once
python -m app.worker.run aggregate        # pull The Muse / Remotive / Jobicy / Adzuna
python -m app.worker.run discover         # probe candidate slugs, register live boards
python -m app.worker.run discover-search  # harvest ATS identifiers from web search
python -m app.worker.run loop 900         # crawl every 900s
```

`seed` then `crawl` is enough to get a few thousand real jobs locally.
`discover-search` additionally needs `BRAVE_SEARCH_API_KEY`, and `aggregate`
wants `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` for its largest source; both skip
cleanly when the credentials are absent.

## Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # points at http://localhost:8000
npm run dev                        # :3000
```

## Scheduled jobs

Production runs on GitHub Actions, and the workflows in `.github/workflows/` are
the authoritative description of what runs when: an hourly crawl, a daily feed
aggregation, and weekly company discovery.

## Adding an ATS provider

The scraper interface is the only contract the rest of the system depends on, so
this stays a one-file change:

1. Add `backend/app/scrapers/<name>.py` subclassing `BaseScraper`, set
   `provider = ATSProvider.<name>`, decorate it with `@register`, and implement
   `fetch_jobs` to return `NormalizedJob` objects. Scrapers never touch the
   database.
2. Import it in `backend/app/scrapers/__init__.py` — that import is what
   registers it.
3. Add companies using that provider.

Ingest, deduplication, the API and the UI are all provider-agnostic and need no
changes.
