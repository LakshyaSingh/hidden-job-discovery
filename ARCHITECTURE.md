# Hidden Job Discovery Platform — Architecture

> Status: **Phase 1 (Proof of Concept)** — Greenhouse provider, ingest pipeline with
> deduplication, REST API, and a minimal dashboard. Designed so additional ATS
> providers and features drop in without refactoring the core.

## 1. Goals & Guiding Principles

1. **Company career portal is the source of truth.** Posting dates, apply URLs, and
   "newness" are derived from the ATS, never from an aggregator. A job that LinkedIn
   "reposted 5 hours ago" but that has lived on the company's Greenhouse board for
   three weeks is treated as **old**.
2. **Modular by provider.** Every ATS has one scraper module implementing a single
   interface (`BaseScraper`). Adding Workday means adding one file + one registry entry.
3. **Incremental & cheap crawling.** We fingerprint content and skip unchanged pages;
   we upsert rather than rewrite; we only mark jobs "new" on genuine first discovery.
4. **Separation of concerns.** Discovery (scrapers) → Normalization (extractors) →
   Ingestion (dedup + persistence) → API → UI. Each layer is independently testable.

## 2. High-Level System Diagram

```
                    ┌─────────────────────────────────────────────┐
                    │                Frontend (Next.js)            │
                    │   Dashboard: search / filter / sort /        │
                    │   bookmark / hide / mark-applied             │
                    └───────────────────────┬─────────────────────┘
                                             │ REST (JSON)
                    ┌───────────────────────▼─────────────────────┐
                    │              Backend API (FastAPI)           │
                    │   /jobs  /companies  /searches  /crawl       │
                    └───────────┬─────────────────────┬───────────┘
                                │                     │
                   ┌────────────▼─────────┐   ┌───────▼───────────┐
                   │   Ingest Service     │   │   PostgreSQL      │
                   │   dedup + upsert +   │◄──┤   (SQLAlchemy)    │
                   │   change detection   │   └───────────────────┘
                   └────────────▲─────────┘
                                │ NormalizedJob objects
                   ┌────────────┴──────────────────────────────────┐
                   │            Crawl Orchestrator (worker)         │
                   │   schedules per-company crawl tasks            │
                   └────────────┬──────────────────────────────────┘
                                │ implements BaseScraper
        ┌───────────────────────┼───────────────────────────────────┐
        ▼                       ▼                                     ▼
 ┌─────────────┐        ┌──────────────┐                     ┌──────────────┐
 │ Greenhouse  │        │  Lever (TODO)│      ...             │ Workday(TODO)│
 │  (HTTP API) │        │  (HTTP API)  │                     │ (Playwright) │
 └─────────────┘        └──────────────┘                     └──────────────┘
```

## 3. Component Responsibilities

| Layer | Responsibility | Key files |
|---|---|---|
| **Scrapers** | Fetch raw postings from one ATS, emit `NormalizedJob` objects. No DB access. | `app/scrapers/*` |
| **Extractors** | Pure functions: experience range, skills, location type, salary, title normalization. | `app/scrapers/extract.py` |
| **Ingest** | Deduplicate, upsert, detect changes, flag `is_new`, close stale jobs. | `app/services/ingest.py` |
| **Orchestrator** | Iterate companies, call the right scraper, hand results to ingest, record run stats. | `app/services/crawl.py` |
| **API** | Query/filter/sort jobs; manage user state (bookmark/hide/applied); trigger crawls. | `app/api/*` |
| **Frontend** | Dashboard over the API. | `frontend/` |

## 4. The Scraper Interface

Every provider implements `BaseScraper`:

```python
class BaseScraper(ABC):
    provider: ClassVar[ATSProvider]

    @abstractmethod
    async def fetch_jobs(self, company: CompanyRef) -> list[NormalizedJob]: ...

    # optional: fetch a single job's full description lazily
    async def fetch_detail(self, company: CompanyRef, external_id: str) -> NormalizedJob | None: ...
```

- Input: a `CompanyRef` (name + the ATS identifier, e.g. a Greenhouse board token).
- Output: a list of `NormalizedJob` dataclasses — the **only** contract the rest of the
  system depends on. Providers are free to use HTTP APIs (Greenhouse, Lever, Ashby) or
  Playwright (Workday, iCIMS) internally.
- Providers self-register via `@register` so the orchestrator can look one up by enum.

This is the seam that makes "add a provider" a one-file change.

## 5. Deduplication & "Newness" — the core intellectual problem

Two distinct dedup problems:

1. **Same job, same ATS, seen again on re-crawl** → keyed by `(company_id, external_id)`
   unique constraint. We *upsert*: update `last_seen_at`, refresh mutable fields, and
   only touch `is_new`/`first_discovered_at` on genuine insert.

2. **Same job across sources / cross-ATS / aggregator reposts** → keyed by a
   **content fingerprint**: `sha1(normalized_company + normalized_title + location_bucket)`.
   Stored on every job. If a new candidate collides with an existing fingerprint whose
   `original_posted_at` is older than the incoming "posted" date, we keep the **older**
   original date. The company portal always wins over an aggregator's repost timestamp.

**"Posted in last 24h"** means `original_posted_at >= now-24h` when the ATS gives us a
real publish date (Greenhouse, Ashby, Lever all do). We fall back to `first_discovered_at`
only when no authoritative date exists, and we flag which one was used (`date_source`).

**Change detection:** each job stores a `content_hash` over its description + key fields.
On re-crawl, if the hash is unchanged we skip re-processing the description (skills/exp
extraction is the expensive part). This is the "avoid re-downloading/re-parsing unchanged
pages" requirement.

**Removal detection:** each crawl run stamps `last_seen_at`. A company sweep that
completes without seeing a previously-open job marks it `status = closed`.

## 6. Database Schema (overview)

See `backend/app/models.py` for the authoritative definition. Core tables:

- **companies** — name, slug, `ats_provider`, `ats_identifier`, careers_url, active.
- **jobs** — everything in the "Job Information to Store" list, plus `content_hash`,
  `content_fingerprint`, `date_source`, `status`, `is_new`, timestamps.
- **job_user_state** — per-job flags (bookmarked/hidden/applied). Split from `jobs` so
  it survives re-crawls and generalizes to multi-user later.
- **saved_searches** — persisted filter sets (powers future notifications).
- **crawl_runs** — one row per company crawl: counts, duration, errors (observability).

`skills` is a JSONB array; salary is stored as `min/max/currency`. Indexes on
`original_posted_at`, `title_normalized`, `content_fingerprint`, `(company_id, external_id)`.

## 7. Scheduling & Scaling (Phase 1 → later)

- **Phase 1:** synchronous orchestrator invoked via CLI (`python -m app.worker.run`)
  or the `/crawl` endpoint. Good enough for tens of companies.
- **Later:** the orchestrator is written to be queue-agnostic — swap the in-process loop
  for Celery/RQ/Arq workers reading a Redis/Vercel-Queues queue, one task per company.
  Rate limiting is per-domain (token bucket in `scrapers/http.py`); retries use
  exponential backoff. Nothing in ingest/API changes.

## 8. Technology Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Backend lang | Python/FastAPI | Node | Scraping ecosystem (Playwright, BS4, lxml) + async HTTP + Pydantic. |
| ORM | SQLAlchemy 2.0 (async) | Prisma | Native to Python; async; mature for complex upserts. |
| DB | PostgreSQL | Supabase | JSONB, upserts, full-text later. Supabase = managed PG, drop-in. |
| Greenhouse fetch | Public JSON API | Playwright | Official, stable, fast, no browser. Reserve Playwright for JS-only ATSes. |
| Dedup key | content fingerprint | ML similarity | Deterministic + cheap now; semantic dedup is a documented Phase-2 upgrade. |
| Deploy | docker-compose (local) | Vercel | FastAPI+Playwright workers are long-running; not a serverless fit. Frontend can go to Vercel. |

## 9. Roadmap

- **Phase 1 (this):** Greenhouse, ingest+dedup, API, dashboard.
- **Phase 2:** Lever + Ashby (HTTP APIs — quick wins), saved-search-driven daily email.
- **Phase 3:** Workday/iCIMS via Playwright; queue-based workers; company discovery.
- **Phase 4:** AI title normalization, semantic search (pgvector), resume match score,
  Slack/Discord/browser notifications, Chrome extension.
