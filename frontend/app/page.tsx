"use client";

import { useCallback, useEffect, useState } from "react";
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

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchJobs(filters);
      setJobs(data.items);
      setTotal(data.total);
    } catch {
      setJobs([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    load();
  }, [load]);

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

  return (
    <div className="container">
      <header className="top">
        <div>
          <h1>Hidden Job Discovery</h1>
          <div className="subtitle">
            New roles straight from company career portals — before the boards.
          </div>
        </div>
        <button className="btn" onClick={runCrawl} disabled={crawling}>
          {crawling ? "Crawling…" : "Run crawl"}
        </button>
      </header>

      <div className="filters">
        <input
          type="text"
          placeholder="Title or keyword (e.g. product manager)"
          value={filters.q ?? ""}
          onChange={(e) => set("q", e.target.value || undefined)}
        />

        <label>
          Exp:
          <input
            className="exp"
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
          –
          <input
            className="exp"
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
        </label>

        <select
          value={filters.location_type ?? ""}
          onChange={(e) =>
            set("location_type", (e.target.value || undefined) as LocationType)
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
        </select>

        <select
          value={filters.sort}
          onChange={(e) => set("sort", e.target.value as JobFilters["sort"])}
        >
          <option value="posted">Sort: posted</option>
          <option value="discovered">Sort: discovered</option>
          <option value="title">Sort: title</option>
          <option value="company">Sort: company</option>
        </select>

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

      <div className="meta-row">
        {loading ? "Loading…" : `${total} job${total === 1 ? "" : "s"} match`}
      </div>

      {!loading && jobs.length === 0 && (
        <div className="empty">
          No jobs yet. Seed companies (<code>python -m app.worker.run seed</code>)
          then click <b>Run crawl</b>.
        </div>
      )}

      {jobs.map((job) => (
        <JobCard key={job.id} job={job} onChange={load} />
      ))}
    </div>
  );
}
