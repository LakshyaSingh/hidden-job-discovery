"use client";

import { Job, updateJobState } from "@/lib/api";
import { useState } from "react";

function timeAgo(iso: string | null): string {
  if (!iso) return "unknown";
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3_600_000);
  if (h < 1) return "just now";
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function experienceLabel(job: Job): string | null {
  if (job.min_experience == null && job.max_experience == null) return null;
  if (job.max_experience == null) return `${job.min_experience}+ yrs`;
  return `${job.min_experience ?? 0}-${job.max_experience} yrs`;
}

function salaryLabel(job: Job): string | null {
  if (!job.salary_min) return null;
  const cur = job.salary_currency ?? "$";
  const fmt = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`);
  return job.salary_max
    ? `${cur}${fmt(job.salary_min)}-${fmt(job.salary_max)}`
    : `${cur}${fmt(job.salary_min)}`;
}

export function JobCard({ job, onChange }: { job: Job; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const state = job.user_state;

  async function toggle(field: "bookmarked" | "hidden" | "applied") {
    setBusy(true);
    try {
      await updateJobState(job.id, { [field]: !state?.[field] });
      onChange();
    } finally {
      setBusy(false);
    }
  }

  const exp = experienceLabel(job);
  const salary = salaryLabel(job);

  return (
    <article className={`job ${state?.applied ? "applied" : ""}`}>
      <div className="job-head">
        <div>
          {job.is_new && <span className="tag-new">New</span>}
          <h3 className="job-title">
            <a href={job.apply_url} target="_blank" rel="noreferrer">
              {job.title}
            </a>
          </h3>
          <div className="job-company">
            {job.company.name}
            {job.careers_url && (
              <>
                {"  "}
                <a href={job.careers_url} target="_blank" rel="noreferrer">
                  careers
                </a>
              </>
            )}
          </div>
        </div>
        <div className="job-posted">
          Posted {timeAgo(job.original_posted_at ?? job.first_discovered_at)}
          {job.date_source === "discovered" && " (est.)"}
        </div>
      </div>

      <div className="job-meta">
        <span>{job.location_type}</span>
        {job.location_raw && <span>{job.location_raw}</span>}
        <span>{job.ats_provider}</span>
        {exp && <span>{exp}</span>}
        {salary && <span>{salary}</span>}
      </div>

      {job.skills.length > 0 && (
        <div className="job-skills">
          {job.skills.slice(0, 6).map((s) => (
            <span key={s}>{s}</span>
          ))}
        </div>
      )}

      <div className="job-actions">
        <button
          className={`action ${state?.bookmarked ? "on" : ""}`}
          disabled={busy}
          onClick={() => toggle("bookmarked")}
        >
          {state?.bookmarked ? "Saved" : "Save"}
        </button>
        <button
          className={`action ${state?.applied ? "on" : ""}`}
          disabled={busy}
          onClick={() => toggle("applied")}
        >
          {state?.applied ? "Applied" : "Mark applied"}
        </button>
        <button
          className="action"
          disabled={busy}
          onClick={() => toggle("hidden")}
        >
          Hide
        </button>
        <a
          className="apply-link"
          href={job.apply_url}
          target="_blank"
          rel="noreferrer"
        >
          Apply
        </a>
      </div>
    </article>
  );
}
