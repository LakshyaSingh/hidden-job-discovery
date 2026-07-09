# Hidden Job Discovery Platform

Discovers newly posted **US** jobs directly from company career portals (ATS
platforms) before they spread to LinkedIn/Indeed, and surfaces them in a clean,
fast dashboard.

- **5 ATS scrapers** (Greenhouse, Lever, Ashby, SmartRecruiters, Workday) behind a
  common interface, **4 aggregator feeds** (The Muse, Remotive, Jobicy, Adzuna), and an
  auto-discovery engine that finds new company boards.
- Deduplicating ingest with source-of-truth posting dates, US-only filtering,
  title-based experience inference, and a role-taxonomy search.
- Deployed: **Vercel** (frontend) + **Render** (API + Postgres) + **GitHub Actions**
  (six-hour crawl / weekly discovery). Live at https://hidden-job-discovery.vercel.app.

> See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the full design and trade-offs.

```
frontend/   Next.js + TypeScript dashboard
backend/    FastAPI + SQLAlchemy + Alembic + scrapers + aggregators + ingest + worker
```

## Quick start

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Easiest local setup uses SQLite (no Postgres needed) — set in .env:
#   DATABASE_URL=sqlite+aiosqlite:///./dev.db
#   AUTO_CREATE_TABLES=true
# (Or `docker compose up -d db` for Postgres, then `alembic upgrade head`.)

python -m app.worker.run seed        # sample companies
python -m app.worker.run discover    # probe candidate slugs -> register live boards
python -m app.worker.run discover-search  # Brave Search -> register ATS boards
python -m app.worker.run aggregate   # pull The Muse / Remotive / Jobicy / Adzuna feeds
python -m app.worker.run crawl       # crawl all active companies now
uvicorn app.main:app --reload        # API on http://localhost:8000  (/docs for OpenAPI)
```
Run continuously with `python -m app.worker.run loop 900` (crawl every 15 min).

### 3. Frontend
```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev                      # dashboard on http://localhost:3000
```

Or run DB + API together with `docker compose up`.

## Tests
```bash
cd backend && pytest             # extraction / dedup / fingerprint logic
```

## Adding an ATS provider
1. Create `backend/app/scrapers/<name>.py` subclassing `BaseScraper`, set
   `provider = ATSProvider.<name>`, decorate with `@register`, implement
   `fetch_jobs` returning `NormalizedJob` objects.
2. Import it in `backend/app/scrapers/__init__.py`.
3. Add companies with that provider. Nothing else changes — ingest, dedup, API,
   and UI are provider-agnostic.

## Key design points
- **Company portal is the source of truth.** Posting dates come from the ATS;
  aggregator reposts can't make an old job look new (see ARCHITECTURE.md §5).
- **Deduplication** on `(company, external_id)` for same-source and a content
  fingerprint for cross-source/reposts.
- **Change detection** via content hash → unchanged postings skip re-parsing.
- **Removal detection** → jobs absent from a completed sweep are closed.
