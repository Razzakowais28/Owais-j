# Owais Job Tracker

Live job board for Saudi Arabia — Riyadh, Jeddah, Dammam, Al Khobar.

**Sources:** LinkedIn · Bayt · NaukriGulf  
**Auto-refresh:** 8:00 AM and 6:00 PM AST daily (via GitHub Actions)

## Setup

1. Add `APIFY_TOKEN` as a GitHub repository secret:
   - Go to **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `APIFY_TOKEN`
   - Value: Your Apify API token (from https://console.apify.com/account/integrations)

2. Enable **GitHub Pages**:
   - Go to **Settings → Pages**
   - Source: `Deploy from a branch`
   - Branch: `main`, folder: `/ (root)`
   - Save — your URL will be `https://Razzakowais28.github.io/owais-jobs/`

3. That's it. GitHub Actions runs the scraper twice daily and pushes new jobs.

## Manual trigger

Go to **Actions → Refresh Jobs → Run workflow** to trigger a manual refresh.
