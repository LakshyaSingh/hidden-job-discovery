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
  return `${job.min_experience ?? 0}–${job.max_experience} yrs`;
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

  return (
    <div className={`job ${state?.applied ? "applied" : ""}`}>
      <div className="row1">
        <div>
          <h3>
            <a href={job.apply_url} target="_blank" rel="noreferrer">
              {job.title}
            </a>
          </h3>
          <div className="company">
            {job.company.name}
            {job.careers_url && (
              <>
                {" · "}
                <a href={job.careers_url} target="_blank" rel="noreferrer">
                  careers
                </a>
              </>
            )}
          </div>
        </div>
        <div style={{ textAlign: "right", color: "var(--muted)", fontSize: 12 }}>
          posted {timeAgo(job.original_posted_at ?? job.first_discovered_at)}
          {job.date_source === "discovered" && " (est.)"}
        </div>
      </div>

      <div className="badges">
        {job.is_new && <span className="badge new">NEW</span>}
        <span className="badge">{job.ats_provider}</span>
        <span className="badge">{job.location_type}</span>
        {job.location_raw && <span className="badge">{job.location_raw}</span>}
        {exp && <span className="badge">{exp}</span>}
        {job.salary_min && (
          <span className="badge">
            {job.salary_currency ?? "$"}
            {job.salary_min}
            {job.salary_max ? `–${job.salary_max}` : ""}
          </span>
        )}
      </div>

      {job.skills.length > 0 && (
        <div className="skills">
          {job.skills.slice(0, 8).map((s) => (
            <span key={s}>{s}</span>
          ))}
        </div>
      )}

      <div className="actions">
        <button
          disabled={busy}
          className={state?.bookmarked ? "on" : ""}
          onClick={() => toggle("bookmarked")}
        >
          {state?.bookmarked ? "★ Bookmarked" : "☆ Bookmark"}
        </button>
        <button
          disabled={busy}
          className={state?.applied ? "on" : ""}
          onClick={() => toggle("applied")}
        >
          {state?.applied ? "✓ Applied" : "Mark applied"}
        </button>
        <button disabled={busy} onClick={() => toggle("hidden")}>
          Hide
        </button>
      </div>
    </div>
  );
}
