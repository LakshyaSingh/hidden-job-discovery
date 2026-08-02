# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Hidden Job Discovery — finds newly posted **US** jobs directly on company ATS portals
before they reach LinkedIn/Indeed. `backend/` is FastAPI + async SQLAlchemy 2.0 +
Alembic; `frontend/` is Next.js 15 App Router + React 19 + TypeScript (no Tailwind —
plain CSS in `frontend/app/globals.css`).

`ARCHITECTURE.md` holds the design rationale; `CODEX_HANDOFF.md` (gitignored, local
only) holds deployment details, env-var tables, and current scale numbers.

## Commands

```bash
# Backend (from backend/, venv active)
pip install -r requirements.txt
uvicorn app.main:app --reload            # API on :8000, OpenAPI at /docs
pytest                                    # all tests
pytest tests/test_ingest.py               # one file
pytest tests/test_ingest.py::test_new_job_flagged_and_persisted   # one test
alembic upgrade head
alembic revision --autogenerate -m "..."  # env.py imports app.models for metadata

# Worker CLI — the only way to run crawls/discovery outside the API
python -m app.worker.run seed             # insert SAMPLE_COMPANIES (idempotent)
python -m app.worker.run crawl            # crawl all active companies once
python -m app.worker.run loop 900         # crawl every 900s
python -m app.worker.run discover         # probe candidate slugs -> register boards
python -m app.worker.run discover-search  # Brave Search -> harvest ATS tokens
python -m app.worker.run aggregate        # pull The Muse / Remotive / Jobicy / Adzuna

# Frontend (from frontend/)
npm run dev      # :3000
npm run build
npm run lint
```

Local dev is easiest on SQLite: set `DATABASE_URL=sqlite+aiosqlite:///./dev.db` and
`AUTO_CREATE_TABLES=true` in `backend/.env`. `docker compose up` runs Postgres + API +
a 15-minute crawl loop instead.

## Architecture

Pipeline: **scrapers/aggregators → NormalizedJob → ingest (dedup + persist) → API → UI.**

- `app/scrapers/*` — one module per ATS (greenhouse, lever, ashby, smartrecruiters,
  workday), each subclassing `BaseScraper`, decorated with `@register`, imported in
  `app/scrapers/__init__.py`. Scrapers never touch the DB; they return
  `NormalizedJob` dataclasses. That dataclass is the **only** contract ingest depends
  on, so adding a provider is a one-file change plus the import.
- `app/scrapers/http.py` — all outbound fetches go through this: per-host throttling
  (`REQUEST_MIN_INTERVAL_SECONDS`) plus retry/backoff. Don't call `httpx` directly
  from a scraper.
- `app/scrapers/extract.py` — pure functions (title normalization, location/US
  classification, experience, salary, skills, `content_hash`, `content_fingerprint`).
  Cheap to unit test; keep new parsing logic here rather than inside a scraper.
- `app/aggregators/*` — broad multi-employer feeds. They are modeled as
  `ATSProvider` enum values too, but ingested via `app/services/aggregate.py`, which
  groups by employer, get-or-creates a `Company` (slug suffixed with the provider so
  it doesn't collide with the employer's real ATS row), and **disables stale-closing**
  — a feed run sees only a slice, so "not seen" ≠ "removed".
- `app/services/ingest.py` — the core logic. Read ARCHITECTURE.md §5 before changing it.
- `app/services/crawl.py` — per-company unit of work, records a `CrawlRun` row; on
  failure it rolls back and continues to the next company.
- `app/services/discovery*.py` — registers new boards only when a probed slug actually
  returns jobs, so bad guesses can't create junk companies.
- `app/api/*` — `/jobs` (query/filter/sort + `PATCH /jobs/{id}/state`), `/companies`,
  `/providers`, `/crawl`. Write endpoints are guarded by `require_admin_key`
  (`X-API-Key`), which is a **no-op when `ADMIN_API_KEY` is empty**.

### Invariants worth preserving

- **The company portal is the source of truth for dates.** `original_posted_at`
  resolves to the *oldest* date across rows sharing a `content_fingerprint`, so an
  aggregator repost can never make an old job look new. `date_source` records whether
  the date was authoritative (`ats`) or inferred from first sight (`discovered`).
- **Two dedup keys:** `(company_id, external_id)` for same-source re-crawls (upsert;
  only genuine inserts set `is_new`/`first_discovered_at`), and `content_fingerprint`
  = `sha1(company + normalized title + location bucket)` for cross-source.
- **Change detection** via `content_hash`; unchanged postings skip re-parsing.
- **Removal detection:** a *completed* sweep that doesn't see a previously-open job
  closes it. An empty fetch must not close anything (see `test_empty_fetch_does_not_close`).
- **US-only is the product scope.** `/jobs` defaults to `us_only=True`, matching
  `is_us IS TRUE` — jobs with an undeterminable country are excluded, not included.
- **Search goes through `app/services/matching.py`.** A query is expanded across a
  curated role-family taxonomy and OR-matched; queries with no family fall back to
  strict all-token AND matching. Extend `ROLE_FAMILIES` rather than loosening the
  matching, and keep families tight (Product Manager ≠ Product Marketing Manager).

## Gotchas

- **`app/models.py` must use `Optional[X]`, not `X | None`.** SQLAlchemy resolves
  `Mapped[...]` annotations at class-creation time, and the dev machine runs Python
  3.9. Elsewhere `from __future__ import annotations` makes `X | None` fine.
- `AUTO_CREATE_TABLES` is `true` locally and **must stay `false` in production** —
  prod schema comes from Alembic. Any model change needs a migration.
- Tests use a per-test SQLite file (`tests/conftest.py::session`) and
  `asyncio_mode = auto`; write `async def test_...` without a marker.
- The datetime helper `_aware()` in `ingest.py` exists because SQLite returns naive
  datetimes from `DateTime(timezone=True)` columns. Normalize before comparing.
- GitHub Actions (`.github/workflows/`) run the crawler against the Render database
  every 6 hours and discovery weekly; the schedules are deliberately sparse to stay
  inside the free Actions minutes. Aggregator caps in `config.py`
  (`*_MAX_JOBS`/`*_MAX_PAGES`) exist to bound growth against the free Postgres size
  limit — don't raise them casually.
- Pushing to `main` auto-deploys both Vercel (frontend, root dir `frontend/`) and
  Render (API, per `render.yaml`).
