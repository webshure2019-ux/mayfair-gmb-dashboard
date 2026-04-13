# Mayfair Gearbox Review Dashboard

Static client-facing dashboard for Mayfair Gearbox's Google Business Profile reviews across all 4 branches, built for Webshure.

## Temporary fallback mode

Google Business Profile API approval is still pending for the production project, so the dashboard currently supports a temporary manual-update workflow.

How it works:

- `data/manual/base-reviews.json` stores a frozen copy of the last good live dataset
- `data/manual/manual-review-additions.csv` is where you add only the new reviews that arrived after that snapshot
- `scripts/build_manual_dataset.py` merges the base snapshot plus manual additions into `data/reviews.json`
- pushes, `deploy_only`, `manual_rebuild`, and scheduled fallback deploys rebuild from those local files instead of relying on a blocked API

This keeps the customer-facing dashboard stable and lets you update it manually until Google approves the official API project.

## What it includes

- Branch-by-branch review totals and current average rating
- Full star distribution for each branch
- Weekly review counts and average rating per branch
- Monthly review counts and average rating per branch
- Owner response rate, written comment rate, and local guide share
- Searchable review comments explorer with date-range filtering
- Daily scheduled refresh for `00:00` Africa/Johannesburg via GitHub Actions
- GitHub Pages deployment so you can send a public link to the customer

## Project structure

- `index.html`: shareable dashboard shell
- `assets/styles.css`: visual design and responsive layout
- `assets/app.js`: client-side rendering and analytics
- `config/branches.json`: branch metadata plus exact Google location resource names
- `scripts/fetch_reviews.py`: live Google Business Profile fetch pipeline
- `scripts/build_manual_dataset.py`: manual fallback builder for temporary review updates
- `scripts/bootstrap_gbp_token.py`: one-time OAuth helper to generate a refresh token
- `scripts/list_gbp_locations.py`: lists accessible GBP accounts and locations
- `scripts/validate_dashboard_data.py`: validates a dataset before publish
- `scripts/generate_demo_data.py`: writes the bundled demo dataset
- `data/reviews.json`: the file the dashboard reads in production
- `data/manual/base-reviews.json`: frozen live snapshot used for manual fallback mode
- `data/manual/manual-review-additions.csv`: simple CSV where you add only new reviews

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

### 3. Enable official Google Business Profile sync

This project now uses the official Google Business Profile APIs instead of Apify.

Prerequisites:

1. A Google Cloud project with these APIs enabled:
   - Google My Business API v4.9
   - My Business Account Management API
   - My Business Business Information API
2. GBP API access approved for that Google Cloud project
3. A Google account that already manages the Mayfair Gearbox Business Profile

Google references:

- https://developers.google.com/my-business/content/overview
- https://developers.google.com/my-business/content/faq
- https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/list
- https://developers.google.com/my-business/reference/accountmanagement/rest/v1/accounts/list
- https://developers.google.com/my-business/reference/businessinformation/rest/v1/accounts.locations/list

### 4. Create the OAuth client and refresh token

Set these local environment variables before running the setup helpers:

```bash
export GBP_CLIENT_ID="your-google-oauth-client-id"
export GBP_CLIENT_SECRET="your-google-oauth-client-secret"
```

Then run:

```bash
python3 scripts/bootstrap_gbp_token.py
```

The script will:

- open Google's OAuth consent flow in your browser
- request the `https://www.googleapis.com/auth/business.manage` scope
- print a refresh token when the flow completes

### 5. Discover the 4 exact GBP location resource names

After you have the refresh token, set it locally:

```bash
export GBP_REFRESH_TOKEN="your-refresh-token"
```

Then run:

```bash
python3 scripts/list_gbp_locations.py
```

That script prints:

- accessible GBP accounts
- accessible locations
- suggested `googleLocationName` matches for the 4 configured Mayfair branches

Update `config/branches.json` by filling each branch's:

```json
"googleLocationName": "accounts/{accountId}/locations/{locationId}"
```

The live fetch will refuse to publish until every selected branch has a `googleLocationName`.

### 6. Add GitHub repository secrets

In the GitHub repo, go to `Settings -> Secrets and variables -> Actions` and add:

- `GBP_CLIENT_ID`
- `GBP_CLIENT_SECRET`
- `GBP_REFRESH_TOKEN`

### 7. Safe test options

The fetch pipeline keeps the same operator-friendly workflow inputs, but now uses GBP instead of Apify.

Useful local options:

- `GBP_DRY_RUN=1`: prints the selected branches and target output paths without making any network call
- `GBP_BRANCH_IDS=jhb-auto`: selects only specific configured branches
- `GBP_MAX_REVIEWS=5`: samples reviews per selected branch
- `GBP_PREVIEW_MODE=1`: writes to `data/preview/` instead of replacing the live dataset

Examples:

```bash
GBP_DRY_RUN=1 python3 scripts/fetch_reviews.py
GBP_PREVIEW_MODE=1 GBP_BRANCH_IDS=pretoria-manual-auto GBP_MAX_REVIEWS=5 python3 scripts/fetch_reviews.py
python3 scripts/fetch_reviews.py
```

Important safety rule:

- sampled or partial-branch datasets are allowed only in preview mode
- the live `data/reviews.json` publish path requires all 4 branches with no `GBP_MAX_REVIEWS` cap

## Manual fallback workflow

Until Google approves the official API project, use this manual path for updates.

### 1. Edit the manual additions CSV

Open:

- `data/manual/manual-review-additions.csv`

Each row is one new review. Required columns:

- `branch_id`
- `reviewer_name`
- `rating`
- `published_at`

Optional columns:

- `comment`
- `owner_response_text`
- `owner_response_date`
- `review_url`
- `review_id`
- `is_local_guide`
- `reviewer_review_count`
- `reviewer_url`
- `language`

Allowed branch IDs:

- `jhb-auto`
- `germiston-commercial`
- `pretoria-manual-auto`
- `jhb-manual`

Date format:

- use `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`

Example row:

```csv
jhb-auto,Jane Smith,5,2026-04-13,Helpful team and fast turnaround.,Thanks Jane for the feedback!,2026-04-13,https://www.google.com/maps/reviews/...,manual-jane-20260413,false,3,,en
```

### 2. Rebuild the dataset locally

From the project folder run:

```bash
python3 scripts/build_manual_dataset.py
python3 scripts/validate_dashboard_data.py data/reviews.json
```

### 3. Deploy it

Option A: push the repo changes

```bash
git add data/reviews.json data/manual/manual-review-additions.csv
git commit -m "Manual Mayfair review update"
git push
```

Option B: if the files are already committed and pushed, open GitHub Actions and run:

- workflow: `Update and Deploy Dashboard`
- `run_mode`: `manual_rebuild`

The workflow will rebuild from the manual files and redeploy the live site.

## Deployment

The workflow in `.github/workflows/update-and-deploy.yml` does two things:

- redeploys the dashboard on each push to `main` or `master`
- refreshes live review data every day at `22:00 UTC`, which is `00:00` in Johannesburg, once the official API project is approved
- until then, scheduled fallback deploys rebuild from the manual base snapshot plus manual additions

If a scheduled Google fetch fails, the workflow reuses the last published live dataset instead of breaking the public site.

Once GitHub Pages is enabled for the repo, GitHub will give you a public URL that you can share with the customer.

## Notes

- The bundled `data/reviews.json` is demo data until the first successful Google Business Profile sync completes.
- The official GBP API path is free from scraper costs, but it still depends on Google approving the project and the OAuth user having profile access.
- Review URLs are left blank by design because the official GBP review payload does not guarantee a public per-review link.
