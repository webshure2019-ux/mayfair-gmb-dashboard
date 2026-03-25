# Mayfair Gearbox Review Dashboard

Static client-facing dashboard for Mayfair Gearbox's Google Business Profile reviews across all 4 branches, built for Webshure.

## What it includes

- Branch-by-branch review totals and current average rating
- Full star distribution for each branch
- Weekly review counts and average rating per branch
- Monthly review counts and average rating per branch
- Owner response rate, written comment rate, local guide share, and low-star share
- Branch leaderboard with portfolio share and 30-day momentum
- Top recurring review themes and a follow-up queue for weaker unanswered reviews
- Searchable review comments explorer with reviewer text visible
- Daily scheduled refresh for `00:00` Africa/Johannesburg via GitHub Actions
- GitHub Pages deployment so you can send a public link to the customer

## Project structure

- `index.html`: shareable dashboard shell
- `assets/styles.css`: visual design and responsive layout
- `assets/app.js`: client-side rendering and analytics
- `config/branches.json`: branch metadata and source URLs
- `scripts/fetch_reviews.py`: live Apify fetch pipeline
- `scripts/generate_demo_data.py`: writes the bundled demo dataset
- `data/reviews.json`: the file the dashboard reads in production

## Setup

### 1. Add the logos

Drop the actual logo files into:

- `assets/brand/mayfair-gearbox-logo.png`
- `assets/brand/webshure-logo.svg`

The dashboard already falls back to styled text if the files are missing.

### 2. Preview locally

From the project folder:

```bash
python3 scripts/generate_demo_data.py
python3 -m http.server 8000
```

Then open `http://localhost:8000`.

### 3. Enable live Apify updates

1. Create a GitHub repository and push this folder.
2. In the GitHub repo, go to `Settings -> Secrets and variables -> Actions`.
3. Add a repository secret named `APIFY_API_TOKEN`.
4. Optional: add repo variables or workflow env values if you want to override:
   - `APIFY_ACTOR_ID`
   - `APIFY_LANGUAGE`
   - `APIFY_MAX_REVIEWS`
   - `APIFY_REVIEWS_SORT`
   - `APIFY_REVIEWS_START_DATE`

By default, `scripts/fetch_reviews.py` uses the official Apify actor `compass/google-maps-reviews-scraper` and sends the 4 Mayfair branch Google Maps search URLs from `config/branches.json`.

Leave `APIFY_MAX_REVIEWS` unset in production if you want a complete branch-by-branch dashboard. That setting is only useful for quick testing.

Safer first-run options:

- `APIFY_DRY_RUN=1`: prints the actor payload without making any network call
- `APIFY_BRANCH_IDS=jhb-auto`: tests only selected branches
- `APIFY_MAX_REVIEWS=1`: performs a low-cost smoke test
- `APIFY_PREVIEW_MODE=1`: writes the fetched output to `data/preview/` instead of replacing the live dashboard data

## Deployment

The workflow in `.github/workflows/update-and-deploy.yml` does two things:

- redeploys the dashboard on each push to `main` or `master`
- refreshes live review data every day at `22:00 UTC`, which is `00:00` in Johannesburg

Once GitHub Pages is enabled for the repo, GitHub will give you a public URL that you can share with the customer.

## Notes

- The workspace I received did not contain the promised logo files, so placeholders are wired in until those are added.
- If a branch resolves to the wrong Google Maps result, replace its `mapsSearchUrl` in `config/branches.json` with the exact public place URL from Google Maps.
- The bundled `data/reviews.json` is demo data until the first successful Apify run completes.
