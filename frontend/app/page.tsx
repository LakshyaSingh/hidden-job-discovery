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
import { GlassBar } from "./GlassBar";

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
  // A failed request used to be swallowed and rendered as an empty result set,
  // so an API that was down for five days looked exactly like a search that
  // matched nothing. The two need to be distinguishable.
  const [error, setError] = useState<string | null>(null);
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
      setError(null);
    } catch (e) {
      if (myId !== reqSeq.current) return;
      setJobs([]);
      setTotal(0);
      setError(
        e instanceof Error && e.message
          ? e.message
          : "Could not reach the API.",
      );
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
    } catch (e) {
      // Without this the rejection was unhandled and the button just stopped
      // spinning, with the reason visible only in the browser console.
      setError(
        e instanceof Error && e.message ? e.message : "Could not start a crawl.",
      );
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
    <>
      {/* Outside .container so the glass bar spans the viewport, and above it
          in the stacking order so it filters the content scrolling beneath. */}
      <GlassBar>
        <span className="wordmark">Hidden Job Discovery</span>
        <div className="topbar-actions">
          <button className="btn ghost" onClick={runCrawl} disabled={crawling}>
            {crawling ? "Crawling…" : "Run crawl"}
          </button>
        </div>
      </GlassBar>

      <div className="container fade-in">
        <section className="masthead">
          <h1 className="display">
            New roles,
            <br />
            before the boards.
          </h1>
          <p className="lede">
            Jobs pulled straight from company ATS portals, surfaced before they
            reach LinkedIn or Indeed.
          </p>
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
              <span className="label">Experience</span>
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
                <span className="label">to</span>
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

        {/* The match count reads better as a quiet line above the list than
            as a display-sized number in the masthead. */}
        <div className="results-head">
          {loading
            ? "Loading"
            : error
              ? "Unavailable"
              : `${total.toLocaleString()} ${total === 1 ? "role" : "roles"}`}
        </div>

        <div className="results">
          {!loading && error && (
            <div className="empty error-state" role="alert">
              <b>Could not reach the job database.</b>
              <p>
                This is a problem on our side, not an empty search. Your filters
                are still applied and nothing has been lost.
              </p>
              <p className="error-detail">{error}</p>
              <button className="btn ghost" onClick={load}>
                Try again
              </button>
            </div>
          )}

          {!loading && !error && jobs.length === 0 && (
            <div className="empty">
              {hasFilters ? (
                <>
                  No jobs match your filters. Try setting the date to{" "}
                  <b>Any time</b> or <b>Last 7 days</b>, clearing the search, or
                  widening the experience range.
                </>
              ) : (
                <>
                  No jobs yet. The crawler runs automatically every hour, so
                  check back shortly or click <b>Run crawl</b>.
                </>
              )}
            </div>
          )}

          {jobs.map((job) => (
            <JobCard key={job.id} job={job} onChange={load} />
          ))}
        </div>
      </div>
    </>
  );
}
