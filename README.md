# Hidden Job Discovery

**Finds US jobs on company career pages before they reach LinkedIn or Indeed.**

[**hidden-job-discovery.vercel.app**](https://hidden-job-discovery.vercel.app)

[![Crawl](https://github.com/LakshyaSingh/hidden-job-discovery/actions/workflows/crawl.yml/badge.svg)](https://github.com/LakshyaSingh/hidden-job-discovery/actions/workflows/crawl.yml)
[![Aggregate](https://github.com/LakshyaSingh/hidden-job-discovery/actions/workflows/aggregate.yml/badge.svg)](https://github.com/LakshyaSingh/hidden-job-discovery/actions/workflows/aggregate.yml)

---

## Why this exists

By the time a job shows up on a big job board, it is usually not new. It has been
sitting on the company's own careers page for days or weeks, and it already has
hundreds of applicants.

Worse, the boards actively obscure this. "Posted 5 hours ago" on an aggregator
means *the aggregator noticed it* 5 hours ago. The posting itself might be three
weeks old. The single most useful signal for a job seeker — how early am I? — is
the one the boards are least able to give you.

This project goes to the source instead. Companies publish their openings through
applicant tracking systems, and most of those systems have a public API. So rather
than reading a board that read the company, it reads the company.

## What it does

It watches a few hundred company career portals directly and asks each one, every
hour, what has changed. New postings are recorded with the date the *company*
published them, deduplicated against everything already seen, and made searchable.

Roughly, as of August 2026:

| | |
|---|---|
| US jobs tracked | ~22,900 |
| Posted in the last week | ~3,400 |
| Company career portals crawled | ~330 |
| Crawl frequency | hourly |

Coverage spans five ATS platforms — Greenhouse, Lever, Ashby, SmartRecruiters and
Workday — plus four broad job feeds that fill in employers too small to run their
own board.

## The interesting problems

Most of the work here is not scraping. It is deciding what a posting *is*.

**Whose date do you trust?** The same job can be seen on a company's Greenhouse
board, and again through an aggregator that reindexed it last night. Take the
aggregator's word and a three-week-old posting looks brand new, which defeats the
entire point. So every job carries a fingerprint, and its recorded publish date
resolves to the *oldest* date across everything sharing that fingerprint. A repost
can never make an old job look fresh. Each job also records whether its date came
from the company or was inferred from when we first saw it.

**When is a job the same job?** Two different problems wearing one word.
Re-crawling the same board needs an exact key, so postings are keyed on
`(company, id-from-the-ATS)`. Recognising one job across *different* sources needs
something fuzzier, so there is a second key built from the company, a normalised
title, and a location bucket.

**How do you find the companies?** There is no directory of every company using
Greenhouse. The system searches the open web for public posting URLs, extracts the
board identifier out of them, then verifies each candidate against the real ATS API
before registering anything. A wrong guess simply fails to verify, so bad data
cannot leak in. One recent run turned 192 harvested identifiers into 159 verified
new companies.

**How do you know a job is gone?** A sweep that completes without seeing a
previously-open posting closes it. A sweep that fails partway, or returns nothing
at all, must close nothing — otherwise a single bad request silently empties the
board.

**Searching titles nobody agrees on.** "Product Manager", "Product Lead", "Group
PM" and "Head of Product" are one search to a person and four strings to a
database. Queries expand across a curated taxonomy of role families, kept
deliberately tight, because Product Manager and Product Marketing Manager are *not*
the same job.

## How it runs

A Python service crawls and normalises; a small web app reads the results. Both run
on free hosting. The crawler works on a schedule rather than on demand, so the site
answers from a database that is already warm instead of scraping while you wait.

The design decisions and their trade-offs are written up in
[ARCHITECTURE.md](ARCHITECTURE.md). To run it yourself, see
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Scope and caveats

- **US roles only.** Postings whose country cannot be determined are excluded
  rather than guessed at.
- **Single user.** There are no accounts; saved and hidden jobs are global.
- **Only what is public.** Every source is a documented public API or feed. Nothing
  behind a login is touched, and requests are rate-limited per host.
- A personal project, not affiliated with any of the platforms it reads.
