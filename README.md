# Hidden Job Discovery Platform

Discovers newly posted jobs directly from company career portals (ATS platforms)
before they spread to LinkedIn/Indeed, and surfaces them in a clean dashboard.

**Phase 1 (this repo):** Greenhouse provider, deduplicating ingest pipeline with
source-of-truth posting dates, a filterable REST API, and a Next.js dashboard.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design and trade-offs.

```
frontend/   Next.js + TypeScript dashboard
backend/    FastAPI + SQLAlchemy + scrapers + ingest + worker
```

## Quick start

### 1. Database
```bash
docker compose up -d db          # Postgres on localhost:5432
```

### 2. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

python -m app.worker.run seed    # add sample Greenhouse boards
python -m app.worker.run crawl   # discover jobs now
uvicorn app.main:app --reload    # API on http://localhost:8000  (/docs for OpenAPI)
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
