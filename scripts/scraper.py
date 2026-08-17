#!/usr/bin/env python3
"""
Data refresh script. Runs on a schedule via GitHub Actions (8 AM & 6 PM AST).
Manual refresh: Actions → Sync → Run workflow, or push any non-data change to main.
"""

import os, json, time, hashlib, re, requests
from datetime import datetime, timedelta, timezone

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
BASE = "https://api.apify.com/v2"

TARGET_CITIES = {"riyadh", "jeddah", "dammam", "al khobar", "khobar", "al-khobar"}
KEYWORDS = [
    "full stack developer",
    "software engineer react node",
    "frontend developer react",
    "ERP developer",
    "nodejs developer",
]

MAX_AGE_DAYS = 7
MAX_JOBS = 10
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
JOBS_FILE = os.path.join(DATA_DIR, "items.json")
SEEN_FILE = os.path.join(DATA_DIR, "seen.json")

DEV_TITLE = re.compile(
    r"\b("
    r"developer|software engineer|full[\s-]?stack|front[\s-]?end|back[\s-]?end|"
    r"web developer|mobile developer|react|node\.?js|erp\s*developer|erpnext|"
    r"programmer|\.net developer|java developer|python developer|android developer|"
    r"ios developer|flutter developer|product engineer"
    r")\b",
    re.I,
)
SKIP_TITLE = re.compile(
    r"\b(director|manager|head of|lead recruiter|support engineer|network engineer|"
    r"cyber\s*security|security engineer|sales|marketing|hr |human resources|"
    r"accountant|finance|legal)\b",
    re.I,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def job_key(title, company):
    s = f"{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.md5(s.encode()).hexdigest()[:12]

def city_match(location_str):
    loc = (location_str or "").lower()
    return any(c in loc for c in TARGET_CITIES)

def posted_within(posted, days=MAX_AGE_DAYS):
    if not posted:
        return False
    try:
        d = datetime.strptime(str(posted)[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    return d >= cutoff

def is_developer_role(title):
    t = title or ""
    if SKIP_TITLE.search(t):
        return False
    return bool(DEV_TITLE.search(t))

def keep_top_developer_jobs(jobs, limit=MAX_JOBS):
    dev_jobs = [j for j in jobs if is_developer_role(j.get("title", ""))]
    dev_jobs.sort(key=lambda j: j.get("postedDate", ""), reverse=True)
    return dev_jobs[:limit]

def pick_rotated_jobs(scraped, previous_ids, limit=MAX_JOBS):
    """Prefer developer roles not already on the board, then backfill by date."""
    pool = [j for j in scraped if is_developer_role(j.get("title", ""))]
    pool.sort(key=lambda j: j.get("postedDate", ""), reverse=True)
    prev = set(previous_ids or [])
    picked = [j for j in pool if j["id"] not in prev][:limit]
    if len(picked) < limit:
        seen = {j["id"] for j in picked}
        for j in pool:
            if len(picked) >= limit:
                break
            if j["id"] not in seen:
                picked.append(j)
                seen.add(j["id"])
    return picked[:limit]

def dedupe_jobs(jobs):
    seen_ids = set()
    seen_titles = set()
    out = []
    for j in jobs:
        jid = j.get("id")
        tc = f"{j.get('title', '').strip()}|{j.get('company', '').strip()}"
        if not jid or jid in seen_ids or tc in seen_titles:
            continue
        seen_ids.add(jid)
        seen_titles.add(tc)
        out.append(j)
    return out

def run_actor(actor_slug, input_body, wait_secs=120):
    """Start an Apify actor run, wait for completion, return dataset items."""
    actor_id = actor_slug.replace("/", "~")
    url = f"{BASE}/acts/{actor_id}/runs"
    r = requests.post(url, params={"token": APIFY_TOKEN}, json=input_body, timeout=30)
    r.raise_for_status()
    run = r.json()["data"]
    run_id = run["id"]
    dataset_id = run["defaultDatasetId"]
    print(f"  started run {run_id} for {actor_slug}")

    deadline = time.time() + wait_secs
    while time.time() < deadline:
        time.sleep(10)
        st = requests.get(f"{BASE}/actor-runs/{run_id}", params={"token": APIFY_TOKEN}, timeout=15)
        status = st.json()["data"]["status"]
        print(f"  [{actor_slug}] status={status}")
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            break

    items_url = f"{BASE}/datasets/{dataset_id}/items"
    items_r = requests.get(items_url, params={
        "token": APIFY_TOKEN,
        "clean": "true",
        "limit": 200,
        "fields": "title,companyName,location,postedAt,link,applyUrl,employmentType,locationCity,locationCountry,datePosted,jobUrl,applyButtonUrl"
    }, timeout=30)
    return items_r.json() if items_r.ok else []


# ── scrapers ─────────────────────────────────────────────────────────────────

def scrape_linkedin(keyword, location):
    print(f"LinkedIn: {keyword!r} in {location!r}")
    try:
        items = run_actor("curious_coder/linkedin-jobs-scraper", {
            "keywords": keyword,
            "location": location,
            "datePosted": "pastWeek",
            "limitPerSource": 30,
            "scrapeCompany": False,
        })
        results = []
        for j in items:
            loc = j.get("location", "")
            if not city_match(loc):
                continue
            city = next((c.title() for c in TARGET_CITIES if c in loc.lower()), loc.split(",")[0].strip())
            if city.lower() == "khobar":
                city = "Al Khobar"
            results.append({
                "id": job_key(j.get("title",""), j.get("companyName","")),
                "title": j.get("title", ""),
                "company": j.get("companyName", ""),
                "location": loc,
                "city": city,
                "platform": "LinkedIn",
                "postedDate": (j.get("postedAt") or "")[:10],
                "applyUrl": j.get("applyUrl") or j.get("link", ""),
                "jobUrl": j.get("link", ""),
            })
        return results
    except Exception as e:
        print(f"  LinkedIn error: {e}")
        return []

def scrape_bayt(keyword, city):
    print(f"Bayt: {keyword!r} in {city!r}")
    try:
        region_map = {"Riyadh": "saudi-arabia", "Jeddah": "saudi-arabia",
                      "Dammam": "saudi-arabia", "Al Khobar": "saudi-arabia"}
        items = run_actor("memo23/bayt-scraper", {
            "searchJobKeyword": keyword,
            "searchLocation": city,
            "searchCountryRegion": region_map.get(city, "saudi-arabia"),
            "searchPostedWithin": "past_7_days",
            "searchSortBy": "date",
        })
        results = []
        for j in items:
            loc_city = j.get("locationCity", "") or j.get("basicInfo", {}).get("location", "")
            if not city_match(loc_city + " " + city):
                loc_city = city
            results.append({
                "id": job_key(j.get("title",""), j.get("companyName","")),
                "title": j.get("title", ""),
                "company": j.get("companyName", ""),
                "location": f"{loc_city}, Saudi Arabia",
                "city": city,
                "platform": "Bayt",
                "postedDate": (j.get("datePosted") or "")[:10],
                "applyUrl": j.get("applyUrl", ""),
                "jobUrl": j.get("applyUrl", ""),
            })
        return results
    except Exception as e:
        print(f"  Bayt error: {e}")
        return []

def scrape_naukrigulf(keyword, city):
    print(f"NaukriGulf: {keyword!r} in {city!r}")
    try:
        items = run_actor("unfenced-group/naukrigulf-scraper", {
            "keyword": keyword,
            "location": city,
            "country": "Saudi Arabia",
            "daysOld": 7,
            "maxResults": 25,
            "fetchDetails": False,
        })
        results = []
        for j in items:
            loc = j.get("location", "") or city
            if not city_match(loc + " " + city):
                loc = city
            results.append({
                "id": job_key(j.get("title",""), j.get("company","")),
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "location": f"{city}, Saudi Arabia",
                "city": city,
                "platform": "NaukriGulf",
                "postedDate": (j.get("postedDate") or j.get("datePosted") or "")[:10],
                "applyUrl": j.get("applyUrl") or j.get("url", ""),
                "jobUrl": j.get("url") or j.get("applyUrl", ""),
            })
        return results
    except Exception as e:
        print(f"  NaukriGulf error: {e}")
        return []


# ── main ─────────────────────────────────────────────────────────────────────

def scrape_all():
    raw = []

    for kw in [
        "full stack developer",
        "software engineer react nodejs",
        "frontend developer",
        "backend developer",
        "ERP developer",
    ]:
        for city in ["Riyadh, Saudi Arabia", "Jeddah, Saudi Arabia", "Dammam, Saudi Arabia"]:
            raw.extend(scrape_linkedin(kw, city))

    for kw in ["software developer", "full stack developer", "web developer react"]:
        for city in ["Riyadh", "Jeddah", "Dammam", "Al Khobar"]:
            raw.extend(scrape_bayt(kw, city))

    for kw in ["software developer", "full stack developer react", "frontend developer"]:
        for city in ["Riyadh", "Jeddah"]:
            raw.extend(scrape_naukrigulf(kw, city))

    filtered = []
    for j in raw:
        if not j.get("title") or not j.get("company"):
            continue
        if not is_developer_role(j["title"]):
            continue
        if not posted_within(j.get("postedDate")):
            continue
        filtered.append(j)

    filtered = dedupe_jobs(filtered)
    print(f"\nFound {len(raw)} raw jobs → {len(filtered)} developer roles after filter/dedup")
    return filtered


def main():
    if not APIFY_TOKEN:
        print("ERROR: APIFY_TOKEN is not set.")
        print("Add a repository secret named APIFY_TOKEN at:")
        print("  GitHub repo → Settings → Secrets and variables → Actions → Secrets tab")
        print("Use your personal API token from https://console.apify.com/account/integrations")
        raise SystemExit(1)

    scraped = scrape_all()
    merged = keep_top_developer_jobs(scraped)

    jobs_data = {
        "jobs": merged,
        "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    save_json(JOBS_FILE, jobs_data)

    seen_data = {
        "seenIds": [j["id"] for j in merged],
        "seenTitlesCompanies": [
            f"{j['title'].strip()}|{j['company'].strip()}" for j in merged
        ],
    }
    save_json(SEEN_FILE, seen_data)

    print(f"Done. Refreshed feed with {len(merged)} developer roles (max {MAX_JOBS}).")

if __name__ == "__main__":
    main()
