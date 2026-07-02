"""Pure extraction & normalization functions.

Deterministic, dependency-free, unit-testable. AI-based versions of experience
extraction and title normalization are documented Phase-4 upgrades that can
replace these functions behind the same signatures.
"""
from __future__ import annotations

import hashlib
import html as _html
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from app.models import LocationType


def html_to_text(raw: str | None) -> str | None:
    """Convert an HTML job description to readable plain text."""
    if not raw:
        return None
    soup = BeautifulSoup(_html.unescape(raw), "html.parser")
    text = soup.get_text(separator="\n").strip()
    return text or None

# --- Title normalization -----------------------------------------------------

# Common abbreviations & seniority markers collapsed so "Sr. PM" ~ "senior product
# manager" and the search can match close variations rather than exact strings.
_TITLE_SYNONYMS = {
    r"\bsr\.?\b": "senior",
    r"\bjr\.?\b": "junior",
    r"\bpm\b": "product manager",
    r"\bapm\b": "associate product manager",
    r"\btpm\b": "technical product manager",
    r"\bpmm\b": "product marketing manager",
    r"\beng\b": "engineer",
    r"\bmgr\b": "manager",
}


def normalize_title(title: str) -> str:
    """Lowercase, expand abbreviations, strip punctuation/roman-ish noise.

    Used both for storage (title_normalized) and for query-time fuzzy matching.
    """
    t = title.lower().strip()
    for pattern, repl in _TITLE_SYNONYMS.items():
        t = re.sub(pattern, repl, t)
    t = re.sub(r"[\(\[].*?[\)\]]", " ", t)  # drop bracketed suffixes
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# --- Location classification -------------------------------------------------

_REMOTE_RE = re.compile(r"\bremote\b", re.I)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.I)
_ONSITE_RE = re.compile(r"\b(on[\s-]?site|in[\s-]?office|in[\s-]?person)\b", re.I)


def classify_location(location_raw: str | None) -> LocationType:
    if not location_raw:
        return LocationType.unknown
    if _HYBRID_RE.search(location_raw):
        return LocationType.hybrid
    if _REMOTE_RE.search(location_raw):
        return LocationType.remote
    if _ONSITE_RE.search(location_raw):
        return LocationType.onsite
    # A concrete city/state with no remote/hybrid marker → treat as on-site.
    return LocationType.onsite if location_raw.strip() else LocationType.unknown


def location_type_from_workplace(
    workplace_type: str | None,
    is_remote: bool | None = None,
    location_raw: str | None = None,
) -> LocationType:
    """Map an ATS-native workplace field (Lever/Ashby expose one) to our enum,
    falling back to the boolean flag and then to text classification."""
    if workplace_type:
        wt = workplace_type.strip().lower().replace("-", "").replace(" ", "")
        if wt == "remote":
            return LocationType.remote
        if wt == "hybrid":
            return LocationType.hybrid
        if wt in ("onsite", "inperson", "inoffice"):
            return LocationType.onsite
    if is_remote:
        return LocationType.remote
    return classify_location(location_raw)


# --- Datetime parsing --------------------------------------------------------

def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string across provider quirks (trailing Z, 3-digit
    fractional seconds that Python 3.9's fromisoformat rejects)."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    # Normalize fractional seconds to 6 digits for 3.9 compatibility.
    text = re.sub(
        r"\.(\d{1,6})(\d*)",
        lambda m: "." + m.group(1).ljust(6, "0"),
        text,
        count=1,
    )
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


_RELATIVE_DAYS_RE = re.compile(r"(\d+)\s*\+?\s*days?\s*ago", re.I)


def parse_relative_posted(text: str | None, *, now: datetime | None = None) -> datetime | None:
    """Parse Workday-style relative posting text ("Posted Today", "Posted 3 Days
    Ago", "Posted 30+ Days Ago") into an approximate UTC datetime.

    Day-granular only — this is the best the Workday *listing* exposes. Good
    enough for the 24h/48h/7d filters; document as approximate.
    """
    if not text:
        return None
    ref = now or datetime.now(timezone.utc)
    lowered = text.lower()
    if "today" in lowered or "just posted" in lowered:
        return ref
    if "yesterday" in lowered:
        return ref - timedelta(days=1)
    m = _RELATIVE_DAYS_RE.search(lowered)
    if m:
        return ref - timedelta(days=int(m.group(1)))
    return None


def parse_epoch_ms(value: int | float | None) -> datetime | None:
    """Parse an epoch-milliseconds timestamp (Lever's createdAt) to UTC."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


# --- Salary parsing ----------------------------------------------------------

_SALARY_NUM_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?")


def parse_salary_summary(
    text: str | None,
) -> tuple[float | None, float | None, str | None]:
    """Extract (min, max, currency) from a summary like "$191K – $291K".

    Returns (None, None, None) if no dollar figure is present. Only USD ($) is
    recognized in Phase 1; other currencies fall through as unparsed.
    """
    if not text or "$" not in text:
        return None, None, None
    values: list[float] = []
    for num, suffix in _SALARY_NUM_RE.findall(text):
        try:
            amount = float(num.replace(",", ""))
        except ValueError:
            continue
        if suffix.lower() == "k":
            amount *= 1_000
        elif suffix.lower() == "m":
            amount *= 1_000_000
        values.append(amount)
    if not values:
        return None, None, None
    lo = min(values)
    hi = max(values)
    return lo, (hi if hi != lo else None), "USD"


# --- Experience extraction ---------------------------------------------------

# Matches "3+ years", "2-4 years", "minimum of 5 years", "at least 1 year".
_YEARS_RANGE_RE = re.compile(
    r"(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})\s*\+?\s*years?", re.I
)
_YEARS_MIN_RE = re.compile(
    r"(?:minimum(?:\s+of)?|at\s+least|>=?)?\s*(\d{1,2})\s*\+?\s*years?", re.I
)


def extract_experience(text: str | None) -> tuple[int | None, int | None]:
    """Return (min_years, max_years) inferred from a description. None if absent."""
    if not text:
        return None, None
    lowered = text.lower()

    ranges = _YEARS_RANGE_RE.findall(lowered)
    if ranges:
        lows = [int(a) for a, _ in ranges]
        highs = [int(b) for _, b in ranges]
        return min(lows), max(highs)

    mins = [int(m) for m in _YEARS_MIN_RE.findall(lowered) if int(m) <= 40]
    if mins:
        lo = min(mins)
        # "3+ years" implies an open-ended upper bound; leave max as None.
        return lo, None
    return None, None


# --- Skills extraction -------------------------------------------------------

# Seed dictionary. Phase-4 replaces this with embedding/LLM extraction.
_SKILL_VOCAB = [
    "python", "javascript", "typescript", "react", "node.js", "sql", "postgresql",
    "aws", "gcp", "azure", "kubernetes", "docker", "figma", "jira", "sql",
    "a/b testing", "roadmap", "agile", "scrum", "analytics", "tableau", "looker",
    "product strategy", "user research", "go-to-market", "stakeholder management",
    "api", "machine learning", "data analysis", "excel", "salesforce",
]


def extract_skills(text: str | None) -> list[str]:
    if not text:
        return []
    lowered = text.lower()
    found = {s for s in _SKILL_VOCAB if s in lowered}
    return sorted(found)


# --- Fingerprints & hashes ---------------------------------------------------

def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _location_bucket(location_raw: str | None) -> str:
    """Coarse location key so aggregator reposts with slightly different location
    strings still collide on the fingerprint."""
    loc_type = classify_location(location_raw)
    if loc_type == LocationType.remote:
        return "remote"
    if not location_raw:
        return "unknown"
    # First token (usually the city) lowercased.
    return re.split(r"[,/|]", location_raw.strip())[0].strip().lower()


def content_fingerprint(company_name: str, title: str, location_raw: str | None) -> str:
    """Cross-source identity. Same job on two ATSes / reposted on LinkedIn →
    same fingerprint (see ARCHITECTURE.md §5)."""
    key = f"{company_name.strip().lower()}|{normalize_title(title)}|{_location_bucket(location_raw)}"
    return _sha1(key)


def content_hash(*, title: str, location_raw: str | None, description: str | None,
                 salary_min: float | None, salary_max: float | None) -> str:
    """Change-detection hash. Unchanged hash on re-crawl → skip re-parsing."""
    key = "|".join([
        title.strip(),
        (location_raw or "").strip(),
        (description or "").strip(),
        str(salary_min), str(salary_max),
    ])
    return _sha1(key)
