// Thin typed client for the FastAPI backend.

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type LocationType = "remote" | "hybrid" | "onsite" | "unknown";
export type JobStatus = "open" | "closed";

export interface Company {
  id: number;
  name: string;
  slug: string;
  ats_provider: string;
  careers_url: string | null;
}

export interface UserState {
  bookmarked: boolean;
  hidden: boolean;
  applied: boolean;
  applied_at: string | null;
}

export interface Job {
  id: number;
  title: string;
  company: Company;
  location_raw: string | null;
  location_type: LocationType;
  ats_provider: string;
  apply_url: string;
  careers_url: string | null;
  first_discovered_at: string;
  original_posted_at: string | null;
  date_source: "ats" | "discovered";
  min_experience: number | null;
  max_experience: number | null;
  employment_type: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  skills: string[];
  status: JobStatus;
  is_new: boolean;
  user_state: UserState | null;
}

export interface JobList {
  total: number;
  items: Job[];
}

export interface JobFilters {
  q?: string;
  min_experience?: number;
  max_experience?: number;
  location_type?: LocationType;
  provider?: string;
  posted_within?: "24h" | "48h" | "7d" | "14d" | "30d";
  only_new?: boolean;
  discovered_today?: boolean;
  bookmarked?: boolean;
  applied?: boolean;
  include_hidden?: boolean;
  sort?: "posted" | "discovered" | "title" | "company";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

function toQuery(filters: JobFilters): string {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  return params.toString();
}

export async function fetchJobs(filters: JobFilters): Promise<JobList> {
  const res = await fetch(`${API_URL}/jobs?${toQuery(filters)}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`fetchJobs failed: ${res.status}`);
  return res.json();
}

export async function updateJobState(
  jobId: number,
  patch: Partial<Pick<UserState, "bookmarked" | "hidden" | "applied">>,
): Promise<UserState> {
  const res = await fetch(`${API_URL}/jobs/${jobId}/state`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`updateJobState failed: ${res.status}`);
  return res.json();
}

const ADMIN_KEY_STORAGE = "adminApiKey";

/** Prompt for the admin key (stored locally) so the manual crawl button can
 * authenticate without embedding a secret in the bundle. */
function getAdminKey(forcePrompt = false): string | null {
  if (typeof window === "undefined") return null;
  let key = forcePrompt ? null : window.localStorage.getItem(ADMIN_KEY_STORAGE);
  if (!key) {
    key = window.prompt("Admin API key (from Render → jobscraper-api → Environment):");
    if (key) window.localStorage.setItem(ADMIN_KEY_STORAGE, key);
  }
  return key;
}

export async function triggerCrawl(): Promise<unknown> {
  const key = getAdminKey();
  const res = await fetch(`${API_URL}/crawl`, {
    method: "POST",
    headers: key ? { "X-API-Key": key } : {},
  });
  if (res.status === 401) {
    // Stored key was wrong/rotated — clear it so the next click re-prompts.
    if (typeof window !== "undefined")
      window.localStorage.removeItem(ADMIN_KEY_STORAGE);
    throw new Error("Crawl rejected: invalid admin API key. Try again.");
  }
  if (!res.ok) throw new Error(`triggerCrawl failed: ${res.status}`);
  return res.json();
}
