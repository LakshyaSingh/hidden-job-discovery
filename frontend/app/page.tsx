"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchJobs,
  triggerCrawl,
  Job,
  JobFilters,
  LocationType,
} from "@/lib/api";
import { JobCard } from "./JobCard";

const LOCATION_TYPES: LocationType[] = ["remote", "hybrid", "onsite"];

export default function Dashboard() {
  const [filters, setFilters] = useState<JobFilters>({
    sort: "posted",
    order: "desc",
    limit: 50,
  });
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [crawling, setCrawling] = useState(false);
  // Separate input state so typing is instant; the query only fires after a
  // short pause (debounce) instead of once per keystroke.
  const [searchText, setSearchText] = useState("");
  // Monotonic request id: only the most recent fetch may write to state, so a
  // slow earlier request (e.g. an unfiltered one during a crawl) can't resolve
  // late and clobber the current filtered results.
  const reqSeq = useRef(0);

  const load = useCallback(async () => {
    const myId = ++reqSeq.current;
    setLoading(true);
    try {
      const data = await fetchJobs(filters);
      if (myId !== reqSeq.current) return; // a newer request superseded us
      setJobs(data.items);
      setTotal(data.total);
    } catch {
      if (myId !== reqSeq.current) return;
      setJobs([]);
      setTotal(0);
    } finally {
      if (myId === reqSeq.current) setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    load();
  }, [load]);

  // Debounce the search box → filters.q (300ms after the last keystroke).
  // No-op when unchanged so it never triggers a redundant fetch.
  useEffect(() => {
    const id = setTimeout(() => {
      const q = searchText.trim() || undefined;
      setFilters((f) => (f.q === q ? f : { ...f, q }));
    }, 300);
    return () => clearTimeout(id);
  }, [searchText]);

  function set<K extends keyof JobFilters>(key: K, value: JobFilters[K]) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  function toggleBool(key: keyof JobFilters) {
    setFilters((f) => ({ ...f, [key]: f[key] ? undefined : true }));
  }

  async function runCrawl() {
    setCrawling(true);
    try {
      await triggerCrawl();
      await load();
    } finally {
      setCrawling(false);
    }
  }

  const hasFilters = Boolean(
    filters.q ||
      filters.posted_within ||
      filters.location_type ||
      filters.min_experience != null ||
      filters.max_experience != null ||
      filters.only_new ||
      filters.discovered_today ||
      filters.bookmarked,
  );

  return (
    <div className="container fade-in">
      <header className="topbar">
        <span className="wordmark">Hidden Job Discovery</span>
        <div className="topbar-actions">
          <button className="btn ghost" onClick={runCrawl} disabled={crawling}>
            {crawling ? "Crawling…" : "Run crawl"}
          </button>
        </div>
      </header>

      <section className="masthead">
        <div className="masthead-lead">
          <span className="eyebrow">Live from company career portals</span>
          <h1 className="display">
            New roles,
            <br />
            before the boards.
          </h1>
          <p className="lede">
            Jobs pulled straight from company ATS portals, surfaced before they
            reach LinkedIn or Indeed.
          </p>
        </div>
        <div className="masthead-stat">
          <span className="stat-num">
            {loading ? "…" : total.toLocaleString()}
          </span>
          <span className="eyebrow">{total === 1 ? "role matched" : "roles matched"}</span>
        </div>
      </section>

      <div className="toolbar">
        <input
          className="control search"
          type="text"
          aria-label="Search title or keyword"
          placeholder="Search a title or keyword, e.g. product manager"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
        />

        <div className="toolbar-row">
          <div className="field">
            <span className="eyebrow">Experience</span>
            <div className="exp-group">
              <input
                className="control exp"
                type="number"
                min={0}
                placeholder="min"
                value={filters.min_experience ?? ""}
                onChange={(e) =>
                  set(
                    "min_experience",
                    e.target.value ? Number(e.target.value) : undefined,
                  )
                }
              />
              <span className="eyebrow">to</span>
              <input
                className="control exp"
                type="number"
                min={0}
                placeholder="max"
                value={filters.max_experience ?? ""}
                onChange={(e) =>
                  set(
                    "max_experience",
                    e.target.value ? Number(e.target.value) : undefined,
                  )
                }
              />
            </div>
          </div>

          <select
            className="control"
            aria-label="Location"
            value={filters.location_type ?? ""}
            onChange={(e) =>
              set(
                "location_type",
                (e.target.value || undefined) as LocationType,
              )
            }
          >
            <option value="">Any location</option>
            {LOCATION_TYPES.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>

          <select
            className="control"
            aria-label="Posted within"
            value={filters.posted_within ?? ""}
            onChange={(e) =>
              set(
                "posted_within",
                (e.target.value || undefined) as JobFilters["posted_within"],
              )
            }
          >
            <option value="">Any time</option>
            <option value="24h">Last 24 hours</option>
            <option value="48h">Last 48 hours</option>
            <option value="7d">Last 7 days</option>
            <option value="14d">Last 14 days</option>
            <option value="30d">Last 30 days</option>
          </select>

          <select
            className="control"
            aria-label="Sort by"
            value={filters.sort}
            onChange={(e) => set("sort", e.target.value as JobFilters["sort"])}
          >
            <option value="posted">Sort: posted</option>
            <option value="discovered">Sort: discovered</option>
            <option value="title">Sort: title</option>
            <option value="company">Sort: company</option>
          </select>

          <span className="spacer" />

          <div className="chips">
            <span
              className={`chip ${filters.only_new ? "active" : ""}`}
              onClick={() => toggleBool("only_new")}
            >
              New only
            </span>
            <span
              className={`chip ${filters.discovered_today ? "active" : ""}`}
              onClick={() => toggleBool("discovered_today")}
            >
              Discovered today
            </span>
            <span
              className={`chip ${filters.bookmarked ? "active" : ""}`}
              onClick={() => toggleBool("bookmarked")}
            >
              Bookmarked
            </span>
          </div>
        </div>
      </div>

      <div className="results">
        {!loading && jobs.length === 0 && (
          <div className="empty">
            {hasFilters ? (
              <>
                No jobs match your filters. Try setting the date to{" "}
                <b>Any time</b> or <b>Last 7 days</b>, clearing the search, or
                widening the experience range.
              </>
            ) : (
              <>
                No jobs yet. The crawler runs automatically every 30&nbsp;minutes,
                so check back shortly or click <b>Run crawl</b>.
              </>
            )}
          </div>
        )}

        {jobs.map((job) => (
          <JobCard key={job.id} job={job} onChange={load} />
        ))}
      </div>
    </div>
  );
}
