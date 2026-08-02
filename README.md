# Hidden Job Discovery

Finds US jobs on company career pages before they reach LinkedIn or Indeed.

[hidden-job-discovery.vercel.app](https://hidden-job-discovery.vercel.app)

[![Crawl](https://github.com/LakshyaSingh/hidden-job-discovery/actions/workflows/crawl.yml/badge.svg)](https://github.com/LakshyaSingh/hidden-job-discovery/actions/workflows/crawl.yml)
[![Aggregate](https://github.com/LakshyaSingh/hidden-job-discovery/actions/workflows/aggregate.yml/badge.svg)](https://github.com/LakshyaSingh/hidden-job-discovery/actions/workflows/aggregate.yml)

## The problem

A listing on a large job board is rarely new. It has usually been open on the
company's own careers page for days or weeks before an aggregator indexes it.

Aggregator timestamps obscure this. "Posted 5 hours ago" records when the
aggregator found the listing, not when the employer published it, so a three
week old posting can appear current. Application timing is one of the few
variables a candidate controls, and it is the variable those timestamps lose.

Companies publish openings through applicant tracking systems, most of which
expose a public API. This project reads those APIs directly instead of reading a
board that read them first.

## What it does

Crawls a few hundred company career portals hourly and records what changed.
Each posting is stored with the publication date reported by the employer,
deduplicated against everything seen previously, and indexed for search.

| | |
|---|---|
| US jobs tracked | ~22,900 |
| Posted in the last week | ~3,400 |
| Career portals crawled | ~330 |
| Crawl frequency | hourly |

Sources are five ATS platforms (Greenhouse, Lever, Ashby, SmartRecruiters,
Workday) plus four aggregated feeds, which cover employers too small to run
their own board.

## Design notes

Fetching the data is the straightforward part. The harder problems are in
deciding what a posting is.

**Posting dates.** The same role can appear on a company's Greenhouse board and,
separately, in an aggregator feed that indexed it later. Trusting the most recent
sighting would make an old posting look new. Every job carries a content
fingerprint, and its recorded publication date resolves to the earliest date
across all rows sharing that fingerprint. Each job also records whether its date
came from the ATS or was inferred from first sighting, so an inferred date is
never presented as authoritative.

**Deduplication.** Two cases, handled separately. Re-crawling a single board
needs an exact match, keyed on the company and the ATS's own posting ID.
Recognizing one role across different sources needs tolerance for formatting
differences, so a second key combines the company, a normalized title, and a
location bucket.

**Company discovery.** No index exists of the companies using a given ATS.
Candidate board identifiers are extracted from public posting URLs found through
web search, then verified against the ATS API before any company is registered.
Unverified candidates are discarded, so an incorrect guess cannot introduce a bad
record.

**Removal detection.** A crawl that completes without seeing a previously open
posting marks it closed. A crawl that fails partway, or returns nothing, closes
nothing. Without that distinction a single failed request would empty the board.

**Title search.** Equivalent roles are titled inconsistently across employers:
Product Manager, Product Lead, Group PM, and Head of Product describe one search
intent. Queries expand across a curated taxonomy of role families. The families
are kept narrow, since Product Manager and Product Marketing Manager are distinct
roles rather than variants of one.

## How it runs

A Python service handles crawling and normalization; a TypeScript web app reads
the results. Both run on free hosting. Crawls run on a schedule rather than on
request, so the site serves from an already populated database.

[ARCHITECTURE.md](ARCHITECTURE.md) documents the design decisions and their
trade-offs. [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) covers local setup.

## Scope

- **US roles only.** Postings whose country cannot be determined are excluded
  rather than assumed.
- **Single user.** There are no accounts, and saved or hidden state is global.
- **Public sources only.** Every source is a documented public API or feed.
  Nothing behind authentication is accessed, and requests are rate limited per
  host.
- A personal project, not affiliated with any of the platforms it reads.
