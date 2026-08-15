#!/usr/bin/env python3
"""
Owais Job Tracker – Auto-scraper
Runs via GitHub Actions at 8 AM and 6 PM AST (5 AM and 3 PM UTC).
Calls Apify actors for LinkedIn, Bayt, NaukriGulf.
Filters to Riyadh, Jeddah, Dammam, Al Khobar only.
Skips jobs already in seen.json.
Updates data/jobs.json and data/seen.json.
"""

import os, json, time, hashlib, requests
from datetime import datetime, timezone

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

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
JOBS_FILE = os.path.join(DATA_DIR, "jobs.json")
SEEN_FILE = os.path.join(DATA_DIR, "seen.json")


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

def main():
    if not APIFY_TOKEN:
        print("ERROR: APIFY_TOKEN not set.")
        return

    seen_data = load_json(SEEN_FILE, {"seenIds": [], "seenTitlesCompanies": []})
    seen_ids = set(seen_data.get("seenIds", []))

    jobs_data = load_json(JOBS_FILE, {"jobs": []})
    existing_ids = {j["id"] for j in jobs_data.get("jobs", [])}

    raw = []

    # LinkedIn — all 4 cities
    for kw in ["full stack developer software engineer react nodejs", "ERP developer frontend"]:
        for city in ["Riyadh, Saudi Arabia", "Jeddah, Saudi Arabia", "Dammam, Saudi Arabia"]:
            raw.extend(scrape_linkedin(kw, city))

    # Bayt — Riyadh + Jeddah
    for kw in ["software developer", "full stack developer react"]:
        for city in ["Riyadh", "Jeddah", "Dammam", "Al Khobar"]:
            raw.extend(scrape_bayt(kw, city))

    # NaukriGulf — Riyadh + Jeddah
    for kw in ["software developer full stack react node"]:
        for city in ["Riyadh", "Jeddah"]:
            raw.extend(scrape_naukrigulf(kw, city))

    # De-duplicate and filter seen
    new_jobs = []
    seen_in_this_run = set()
    for j in raw:
        jid = j["id"]
        if not j["title"] or not j["company"]:
            continue
        tc_key = f"{j['title'].strip()}|{j['company'].strip()}"
        if jid in seen_ids or jid in existing_ids or jid in seen_in_this_run:
            continue
        if tc_key in seen_data.get("seenTitlesCompanies", []):
            continue
        seen_in_this_run.add(jid)
        new_jobs.append(j)

    print(f"\nFound {len(raw)} raw jobs → {len(new_jobs)} new after dedup/filter")

    if not new_jobs:
        print("No new jobs — nothing to commit.")
        return

    # Prepend new jobs (newest first)
    jobs_data["jobs"] = new_jobs + jobs_data.get("jobs", [])
    jobs_data["lastUpdated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_json(JOBS_FILE, jobs_data)

    seen_data["seenIds"] = list(seen_ids | {j["id"] for j in new_jobs})
    seen_data["seenTitlesCompanies"] = list(set(
        seen_data.get("seenTitlesCompanies", []) +
        [f"{j['title'].strip()}|{j['company'].strip()}" for j in new_jobs]
    ))
    save_json(SEEN_FILE, seen_data)

    print(f"Done. Added {len(new_jobs)} new jobs. jobs.json updated.")

if __name__ == "__main__":
    main()
