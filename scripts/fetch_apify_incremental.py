#!/usr/bin/env python3
"""Incrementally fetch latest Google reviews from Apify and merge them safely."""

from __future__ import annotations

import hashlib
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[1]
BRANCHES_PATH = ROOT / "config" / "branches.json"
OUTPUT_PATH = ROOT / "data" / "reviews.json"
BASE_DATASET_PATH = ROOT / "data" / "manual" / "base-reviews.json"
MANUAL_REMOVALS_PATH = ROOT / "data" / "manual" / "manual-review-removals.csv"
PREVIEW_OUTPUT_PATH = ROOT / "data" / "preview" / "reviews-preview.json"

API_BASE = "https://api.apify.com/v2"
DEFAULT_ACTOR = "compass/google-maps-reviews-scraper"
DEFAULT_MAX_REVIEWS_PER_BRANCH = 20
MAX_SCHEDULED_REVIEWS_PER_BRANCH = 20
DEFAULT_MONTHLY_REVIEW_WARNING = 5000
DEFAULT_MONTHLY_REVIEW_STOP = 6500
DEFAULT_BILLING_DAYS = 31
FREE_PLAN_REVIEW_PRICE_PER_1000 = 0.60
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}


def main() -> int:
    all_branches = read_json(BRANCHES_PATH)
    selected_branches = filter_branches(all_branches)
    preview_mode = env_flag("APIFY_PREVIEW_MODE")
    dry_run = env_flag("APIFY_DRY_RUN")
    skip_write = env_flag("APIFY_SKIP_WRITE")
    sync_mode = os.getenv("APIFY_SYNC_MODE", "preview" if preview_mode else "incremental").strip().lower()
    actor_id = os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR)
    max_reviews = parse_positive_int(
        os.getenv("APIFY_MAX_REVIEWS"),
        default=DEFAULT_MAX_REVIEWS_PER_BRANCH,
        name="APIFY_MAX_REVIEWS",
    )
    timeout_seconds = parse_positive_int(
        os.getenv("APIFY_TIMEOUT_SECONDS"),
        default=1800,
        name="APIFY_TIMEOUT_SECONDS",
    )

    enforce_selection_safety(
        all_branches=all_branches,
        selected_branches=selected_branches,
        preview_mode=preview_mode,
        dry_run=dry_run,
        sync_mode=sync_mode,
    )
    enforce_apify_limit_safety(
        selected_branches=selected_branches,
        max_reviews=max_reviews,
        preview_mode=preview_mode,
        dry_run=dry_run,
        sync_mode=sync_mode,
    )

    run_input = build_actor_input(selected_branches, max_reviews)
    projected = projected_usage(selected_branches, max_reviews)

    if dry_run:
        print(render_json({
            "actorId": actor_id,
            "mode": "preview" if preview_mode else "live",
            "syncMode": sync_mode,
            "selectedBranchIds": [branch["id"] for branch in selected_branches],
            "maxReviewsPerBranch": max_reviews,
            "projectedMonthlyReviews": projected["monthlyReviews"],
            "projectedMonthlyCostUsd": projected["monthlyCostUsd"],
            "runInput": run_input,
            "writesLiveDataset": not preview_mode and not skip_write,
        }))
        return 0

    token = require_env("APIFY_API_TOKEN")
    run = start_run(actor_id, token, run_input)
    run_id = run["id"]
    run = wait_for_run(run_id, token, timeout_seconds)

    if run.get("status") != "SUCCEEDED":
        print(f"Apify run {run_id} finished with status {run.get('status')}.", file=sys.stderr)
        return 1

    dataset_id = run.get("defaultDatasetId")
    items = fetch_dataset_items(str(dataset_id or ""), token)
    enforce_run_result_safety(items, selected_branches, max_reviews)

    generated_at = datetime.now(timezone.utc).isoformat()
    scraped_reviews, scraped_branch_updates = normalize_apify_items(
        items=items,
        branches=selected_branches,
        fetched_at=generated_at,
    )
    enforce_review_integrity(scraped_reviews, check_fallback_duplicates=True)
    enforce_branch_match_safety(scraped_reviews, selected_branches)

    current_dataset = read_json(OUTPUT_PATH)
    removal_keys = load_manual_removal_keys(MANUAL_REMOVALS_PATH)
    merged_dataset = merge_incremental_dataset(
        current_dataset=current_dataset,
        configured_branches=all_branches,
        scraped_reviews=scraped_reviews,
        scraped_branch_updates=scraped_branch_updates,
        removal_keys=removal_keys,
        actor_id=actor_id,
        run_id=run_id,
        generated_at=generated_at,
        max_reviews=max_reviews,
        projected=projected,
        preview_mode=preview_mode,
    )

    enforce_merge_safety(current_dataset, merged_dataset, removal_keys)

    output_path = PREVIEW_OUTPUT_PATH if preview_mode else OUTPUT_PATH
    print_run_summary(merged_dataset, output_path, scraped_reviews, items, projected, skipped=skip_write)

    if skip_write:
        return 0

    write_json(output_path, merged_dataset)
    if not preview_mode:
        write_json(BASE_DATASET_PATH, merged_dataset)

    return 0


def build_actor_input(branches: List[Dict[str, Any]], max_reviews: int) -> Dict[str, Any]:
    return {
        "startUrls": [{"url": branch["mapsSearchUrl"]} for branch in branches],
        "reviewsSort": "newest",
        "language": os.getenv("APIFY_LANGUAGE", "en"),
        "maxReviews": max_reviews,
    }


def filter_branches(branches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected_ids = [
        branch_id.strip()
        for branch_id in os.getenv("APIFY_BRANCH_IDS", "").split(",")
        if branch_id.strip()
    ]
    if not selected_ids:
        return branches

    branch_lookup = {branch["id"]: branch for branch in branches}
    missing_ids = [branch_id for branch_id in selected_ids if branch_id not in branch_lookup]
    if missing_ids:
        raise KeyError(f"Unknown branch id(s) in APIFY_BRANCH_IDS: {', '.join(sorted(missing_ids))}")

    return [branch_lookup[branch_id] for branch_id in selected_ids]


def enforce_selection_safety(
    all_branches: List[Dict[str, Any]],
    selected_branches: List[Dict[str, Any]],
    preview_mode: bool,
    dry_run: bool,
    sync_mode: str,
) -> None:
    if preview_mode or dry_run:
        return

    if sync_mode == "backfill":
        if not os.getenv("APIFY_BRANCH_IDS", "").strip():
            raise RuntimeError("Apify backfill mode requires APIFY_BRANCH_IDS so it cannot run every branch accidentally.")
        if len(selected_branches) >= len(all_branches):
            raise RuntimeError("Apify backfill mode is only for selected branch updates. Use incremental mode for all branches.")
        return

    if sync_mode not in {"incremental", "scheduled"}:
        raise RuntimeError(
            "Live Apify writes are only allowed for incremental/scheduled syncs. "
            "Use APIFY_PREVIEW_MODE=1 to test other selections."
        )

    if len(selected_branches) != len(all_branches):
        raise RuntimeError(
            "Live Apify incremental sync must include all configured branches so the "
            "dashboard never publishes partial branch coverage."
        )


def enforce_apify_limit_safety(
    selected_branches: List[Dict[str, Any]],
    max_reviews: int,
    preview_mode: bool,
    dry_run: bool,
    sync_mode: str,
) -> None:
    allow_higher = env_flag("APIFY_ALLOW_HIGHER_LIMIT")
    if not allow_higher and max_reviews > MAX_SCHEDULED_REVIEWS_PER_BRANCH:
        raise RuntimeError(
            f"APIFY_MAX_REVIEWS={max_reviews} is blocked. The safe Free-plan cap is "
            f"{MAX_SCHEDULED_REVIEWS_PER_BRANCH} reviews per branch."
        )

    projected = projected_usage(selected_branches, max_reviews)
    warning_limit = parse_positive_int(
        os.getenv("APIFY_MONTHLY_REVIEW_WARNING"),
        DEFAULT_MONTHLY_REVIEW_WARNING,
        "APIFY_MONTHLY_REVIEW_WARNING",
    )
    stop_limit = parse_positive_int(
        os.getenv("APIFY_MONTHLY_REVIEW_STOP"),
        DEFAULT_MONTHLY_REVIEW_STOP,
        "APIFY_MONTHLY_REVIEW_STOP",
    )

    if projected["monthlyReviews"] > stop_limit:
        raise RuntimeError(
            "Projected Apify review volume is above the hard stop limit: "
            f"{projected['monthlyReviews']} projected vs {stop_limit} allowed."
        )

    if projected["monthlyReviews"] > warning_limit:
        print(
            "Warning: projected Apify review volume is above the warning threshold: "
            f"{projected['monthlyReviews']} projected vs {warning_limit} warning.",
            file=sys.stderr,
        )

    if sync_mode == "scheduled" and not preview_mode and not dry_run and max_reviews > MAX_SCHEDULED_REVIEWS_PER_BRANCH:
        raise RuntimeError("Scheduled Apify sync cannot exceed 20 reviews per branch.")


def enforce_run_result_safety(
    items: List[Dict[str, Any]],
    selected_branches: List[Dict[str, Any]],
    max_reviews: int,
) -> None:
    expected_max = len(selected_branches) * max_reviews
    allowed_overfetch = max(10, int(expected_max * 0.20))
    hard_limit = expected_max + allowed_overfetch
    if len(items) > hard_limit:
        raise RuntimeError(
            f"Apify returned {len(items)} items, which is above the guarded run limit "
            f"of {hard_limit}. The dataset was not published."
        )


def enforce_branch_match_safety(
    scraped_reviews: List[Dict[str, Any]],
    selected_branches: List[Dict[str, Any]],
) -> None:
    matched_counts = Counter(review["branchId"] for review in scraped_reviews)
    missing = [branch["id"] for branch in selected_branches if matched_counts.get(branch["id"], 0) == 0]
    if missing:
        raise RuntimeError(
            "Apify returned zero matched reviews for one or more selected branches: "
            + ", ".join(sorted(missing))
        )


def enforce_review_integrity(reviews: List[Dict[str, Any]], check_fallback_duplicates: bool = False) -> None:
    duplicate_keys = [
        key
        for key, count in Counter(review_key(review) for review in reviews).items()
        if count > 1
    ]
    if duplicate_keys:
        raise RuntimeError(
            "Duplicate review IDs were found after normalization: "
            + ", ".join(sorted(duplicate_keys)[:10])
        )

    if check_fallback_duplicates:
        duplicate_fallbacks = [
            key
            for key, count in Counter(fallback_signature(review) for review in reviews).items()
            if count > 1
        ]
        if duplicate_fallbacks:
            raise RuntimeError(
                "Duplicate review signatures were found after normalization. "
                "The dataset was not published because Apify may have returned duplicated reviews."
            )

    invalid_ratings = [
        review_key(review)
        for review in reviews
        if int(first_number(review.get("rating"), 0)) not in {1, 2, 3, 4, 5}
    ]
    if invalid_ratings:
        raise RuntimeError(
            "Invalid review ratings were found after normalization: "
            + ", ".join(sorted(invalid_ratings)[:10])
        )


def enforce_merge_safety(
    current_dataset: Dict[str, Any],
    merged_dataset: Dict[str, Any],
    removal_keys: set[str],
) -> None:
    current_count = len(current_dataset.get("reviews") or [])
    merged_count = len(merged_dataset.get("reviews") or [])
    explained_removals = sum(
        1
        for review in current_dataset.get("reviews") or []
        if review_key(review) in removal_keys
    )
    minimum_expected_count = current_count - explained_removals
    if merged_count < minimum_expected_count:
        raise RuntimeError(
            f"Merged dataset has fewer reviews than expected ({merged_count} < {minimum_expected_count}). "
            "The dataset was not published."
        )

    enforce_review_integrity(merged_dataset.get("reviews") or [])

    branch_ids = {branch.get("id") for branch in merged_dataset.get("branches") or []}
    invalid_branch_reviews = [
        review_key(review)
        for review in merged_dataset.get("reviews") or []
        if review.get("branchId") not in branch_ids
    ]
    if invalid_branch_reviews:
        raise RuntimeError(
            "Merged reviews reference unknown branches: "
            + ", ".join(sorted(invalid_branch_reviews)[:10])
        )


def projected_usage(branches: List[Dict[str, Any]], max_reviews: int) -> Dict[str, Any]:
    billing_days = parse_positive_int(os.getenv("APIFY_BILLING_DAYS"), DEFAULT_BILLING_DAYS, "APIFY_BILLING_DAYS")
    daily_reviews = len(branches) * max_reviews
    monthly_reviews = daily_reviews * billing_days
    monthly_cost = round((monthly_reviews / 1000) * FREE_PLAN_REVIEW_PRICE_PER_1000, 2)
    return {
        "dailyReviews": daily_reviews,
        "monthlyReviews": monthly_reviews,
        "monthlyCostUsd": monthly_cost,
        "billingDays": billing_days,
        "pricePerThousandReviewsUsd": FREE_PLAN_REVIEW_PRICE_PER_1000,
    }


def normalize_apify_items(
    items: Iterable[Dict[str, Any]],
    branches: List[Dict[str, Any]],
    fetched_at: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    normalized_reviews: List[Dict[str, Any]] = []
    branch_updates: Dict[str, Dict[str, Any]] = {}

    for item in items:
        branch = match_branch(item, branches)
        if not branch:
            continue

        branch_updates[branch["id"]] = {
            "currentReviewsCount": first_number(item.get("reviewsCount"), 0),
            "currentRating": first_number(item.get("totalScore"), 0),
            "placeUrl": item.get("url"),
            "placeId": item.get("placeId"),
            "fid": item.get("fid"),
            "imageUrl": item.get("imageUrl"),
        }
        review = normalize_review(item, branch, fetched_at)
        if review:
            normalized_reviews.append(review)

    return normalized_reviews, branch_updates


def normalize_review(item: Dict[str, Any], branch: Dict[str, Any], fetched_at: str) -> Optional[Dict[str, Any]]:
    published_at = item.get("publishedAtDate") or item.get("publishedAt") or item.get("scrapedAt")
    rating = first_number(item.get("stars"), item.get("rating"), 0)
    if not published_at or not rating:
        return None

    review_id = str(item.get("reviewId") or "").strip()
    comment = item.get("text") or ""
    if not review_id:
        review_id = generate_review_id(branch["id"], item.get("name") or "Anonymous reviewer", int(rating), published_at, comment)

    owner_response_date = item.get("responseFromOwnerDate")

    return {
        "id": review_id,
        "branchId": branch["id"],
        "branchName": branch["name"],
        "reviewerName": item.get("name") or "Anonymous reviewer",
        "reviewerUrl": item.get("reviewerUrl"),
        "reviewerReviewCount": int(first_number(item.get("reviewerNumberOfReviews"), 0)),
        "isLocalGuide": bool(item.get("isLocalGuide")),
        "rating": int(rating),
        "comment": comment,
        "commentTranslated": item.get("textTranslated") or "",
        "publishedAt": published_at,
        "updatedAt": item.get("updatedAtDate") or published_at,
        "publishedLabel": item.get("publishAt") or "",
        "reviewUrl": item.get("reviewUrl"),
        "reviewSource": item.get("reviewOrigin") or "Google",
        "ownerResponseText": item.get("responseFromOwnerText") or "",
        "ownerResponseDate": owner_response_date,
        "ownerResponseUpdatedAt": owner_response_date,
        "reviewImageUrls": item.get("reviewImageUrls") or [],
        "language": item.get("originalLanguage") or item.get("language"),
        "translatedLanguage": item.get("translatedLanguage"),
        "scrapedAt": item.get("scrapedAt") or fetched_at,
        "placeId": item.get("placeId") or branch.get("placeId"),
        "cid": item.get("cid") or branch.get("cid"),
        "fid": item.get("fid") or branch.get("fid"),
        "placeUrl": item.get("url") or branch.get("mapsSearchUrl") or branch.get("profileUrl"),
        "title": item.get("title") or branch.get("name"),
    }


def merge_incremental_dataset(
    current_dataset: Dict[str, Any],
    configured_branches: List[Dict[str, Any]],
    scraped_reviews: List[Dict[str, Any]],
    scraped_branch_updates: Dict[str, Dict[str, Any]],
    removal_keys: set[str],
    actor_id: str,
    run_id: str,
    generated_at: str,
    max_reviews: int,
    projected: Dict[str, Any],
    preview_mode: bool,
) -> Dict[str, Any]:
    current_reviews = [
        review for review in (current_dataset.get("reviews") or [])
        if review_key(review) not in removal_keys
    ]
    merged_by_key: Dict[str, Dict[str, Any]] = {}
    fallback_to_key: Dict[str, str] = {}

    for review in current_reviews:
        key = review_key(review)
        existing_key = find_existing_review_key(merged_by_key, review)
        if existing_key:
            merged_by_key[existing_key] = merge_review_values(merged_by_key[existing_key], review)
            continue
        merged_by_key[key] = review
        fallback_to_key[fallback_signature(review)] = key
        fallback_to_key[loose_signature(review)] = key

    for review in scraped_reviews:
        key = review_key(review)
        if key in removal_keys:
            continue

        fallback = fallback_signature(review)
        loose_fallback = loose_signature(review)
        loose_existing_key = fallback_to_key.get(loose_fallback)
        existing_key = (
            key
            if key in merged_by_key
            else fallback_to_key.get(fallback)
            or (
                loose_existing_key
                if loose_existing_key and can_loose_merge(merged_by_key[loose_existing_key], review)
                else None
            )
        )
        if existing_key:
            merged_by_key[existing_key] = merge_review_values(merged_by_key[existing_key], review)
            fallback_to_key[fallback] = existing_key
            fallback_to_key[loose_fallback] = existing_key
        else:
            merged_by_key[key] = review
            fallback_to_key[fallback] = key
            fallback_to_key[loose_fallback] = key

    merged_reviews = list(merged_by_key.values())
    merged_reviews.sort(
        key=lambda review: review.get("publishedAt") or review.get("updatedAt") or review.get("scrapedAt") or "",
        reverse=True,
    )

    reviews_by_branch: Dict[str, List[Dict[str, Any]]] = {branch["id"]: [] for branch in configured_branches}
    for review in merged_reviews:
        if review.get("branchId") in reviews_by_branch:
            reviews_by_branch[review["branchId"]].append(review)

    current_branches_by_id = {branch["id"]: branch for branch in (current_dataset.get("branches") or [])}
    merged_branches: List[Dict[str, Any]] = []
    for branch in configured_branches:
        branch_id = branch["id"]
        current_branch = current_branches_by_id.get(branch_id, {})
        scraped_update = scraped_branch_updates.get(branch_id, {})
        branch_reviews = reviews_by_branch.get(branch_id, [])
        merged_branch = {
            **current_branch,
            **branch,
            "currentReviewsCount": len(branch_reviews),
            "currentRating": round_one_decimal(average(review.get("rating") for review in branch_reviews)),
            "placeUrl": scraped_update.get("placeUrl") or current_branch.get("placeUrl") or branch.get("mapsSearchUrl") or branch.get("profileUrl"),
            "placeId": scraped_update.get("placeId") or current_branch.get("placeId") or branch.get("placeId"),
            "fid": scraped_update.get("fid") or current_branch.get("fid"),
            "imageUrl": scraped_update.get("imageUrl") or current_branch.get("imageUrl"),
            "apifyReportedReviewsCount": int(scraped_update.get("currentReviewsCount") or 0),
            "apifyReportedRating": round_one_decimal(scraped_update.get("currentRating") or 0),
        }
        merged_branches.append(merged_branch)

    scraped_branch_counts = Counter(review["branchId"] for review in scraped_reviews)
    meta = {
        **(current_dataset.get("meta") or {}),
        "mode": "preview" if preview_mode else "live",
        "generatedAt": generated_at,
        "timezone": "Africa/Johannesburg",
        "source": "Apify incremental sync",
        "reviewCount": len(merged_reviews),
        "actorId": actor_id,
        "actorRunId": run_id,
        "apifyMaxReviewsPerBranch": max_reviews,
        "apifyScrapedReviewCount": len(scraped_reviews),
        "apifyScrapedBranchCounts": dict(scraped_branch_counts),
        "apifyProjectedDailyReviews": projected["dailyReviews"],
        "apifyProjectedMonthlyReviews": projected["monthlyReviews"],
        "apifyProjectedMonthlyCostUsd": projected["monthlyCostUsd"],
        "apifyPricePerThousandReviewsUsd": projected["pricePerThousandReviewsUsd"],
        "sampled": False,
    }

    return {
        "meta": meta,
        "branches": merged_branches,
        "reviews": merged_reviews,
    }


def load_manual_removal_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()

    removal_keys: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            branch_id = str(row.get("branch_id") or "").strip()
            review_id = str(row.get("review_id") or "").strip()
            if branch_id and review_id:
                removal_keys.add(f"{branch_id}::{review_id}")
    return removal_keys


def match_branch(item: Dict[str, Any], branches: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    place_id = str(item.get("placeId") or "").strip()
    cid = str(item.get("cid") or "").strip()
    title = normalize_text(item.get("title"))
    branch_list = list(branches)

    for branch in branch_list:
        if place_id and place_id == str(branch.get("placeId") or "").strip():
            return branch

    for branch in branch_list:
        if cid and cid == str(branch.get("cid") or "").strip():
            return branch

    if not title:
        return None

    for branch in branch_list:
        if blocked_title(item.get("title"), branch):
            continue
        candidates = branch_candidates(branch)
        if any(candidate and candidate == title for candidate in candidates):
            return branch

    for branch in branch_list:
        if blocked_title(item.get("title"), branch):
            continue
        candidates = branch_candidates(branch)
        if any(candidate and (title.startswith(candidate) or candidate.startswith(title)) for candidate in candidates):
            return branch

    return None


def branch_candidates(branch: Dict[str, Any]) -> List[str]:
    return [
        normalize_text(alias)
        for alias in [
            *(branch.get("aliases", []) or []),
            branch.get("name"),
            branch.get("shortName"),
            branch.get("searchQuery"),
        ]
        if alias
    ]


def blocked_title(title: Optional[str], branch: Dict[str, Any]) -> bool:
    normalized_title = normalize_text(title)
    blocked_titles = [normalize_text(value) for value in (branch.get("blockedTitles") or []) if value]
    return bool(normalized_title and normalized_title in blocked_titles)


def review_key(review: Dict[str, Any]) -> str:
    return f"{review.get('branchId')}::{review.get('id')}"


def find_existing_review_key(
    reviews_by_key: Dict[str, Dict[str, Any]],
    review: Dict[str, Any],
) -> Optional[str]:
    key = review_key(review)
    if key in reviews_by_key:
        return key

    exact_signature = fallback_signature(review)
    loose = loose_signature(review)
    for existing_key, existing_review in reviews_by_key.items():
        if fallback_signature(existing_review) == exact_signature:
            return existing_key
        if loose_signature(existing_review) == loose and can_loose_merge(existing_review, review):
            return existing_key

    return None


def fallback_signature(review: Dict[str, Any]) -> str:
    return "|".join(
        [
            normalize_text(review.get("branchId")),
            normalize_text(review.get("reviewerName")),
            str(review.get("publishedAt") or "")[:10],
            str(int(first_number(review.get("rating"), 0))),
            normalize_text(review.get("comment")),
        ]
    )


def loose_signature(review: Dict[str, Any]) -> str:
    return "|".join(
        [
            normalize_text(review.get("branchId")),
            normalize_text(review.get("reviewerName")),
            str(review.get("publishedAt") or "")[:10],
            str(int(first_number(review.get("rating"), 0))),
        ]
    )


def merge_review_values(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    existing_source = normalize_text(existing.get("reviewSource"))
    incoming_source = normalize_text(incoming.get("reviewSource"))
    prefer_incoming = incoming_source == "google" and existing_source != "google"
    primary = incoming if prefer_incoming else existing
    secondary = existing if prefer_incoming else incoming
    merged = {**secondary, **primary}

    # Preserve useful manual owner-response data if Apify returns the same review
    # without the full response content.
    for field in ["ownerResponseText", "ownerResponseDate", "ownerResponseUpdatedAt"]:
        if not merged.get(field) and secondary.get(field):
            merged[field] = secondary[field]

    return merged


def can_loose_merge(existing: Dict[str, Any], incoming: Dict[str, Any]) -> bool:
    sources = {
        normalize_text(existing.get("reviewSource")),
        normalize_text(incoming.get("reviewSource")),
    }
    return "manual update" in sources and "google" in sources


def generate_review_id(branch_id: str, reviewer_name: str, rating: int, published_at: str, comment: str) -> str:
    signature = "|".join([branch_id, reviewer_name, str(rating), published_at, comment.strip()])
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]
    return f"apify-{digest}"


def deduplicate_by_id(reviews: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for review in reviews:
        seen[review_key(review)] = review
    return list(seen.values())


def start_run(actor_id: str, token: str, run_input: Dict[str, Any]) -> Dict[str, Any]:
    actor_ref = actor_id.replace("/", "~")
    return apify_request("POST", f"/acts/{actor_ref}/runs", token=token, payload=run_input)


def wait_for_run(run_id: str, token: str, timeout_seconds: int) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    poll_window = min(60, timeout_seconds)

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for Apify run {run_id} after {timeout_seconds} seconds.")

        run = apify_request(
            "GET",
            f"/actor-runs/{run_id}",
            token=token,
            params={"waitForFinish": str(min(poll_window, max(1, int(remaining))))},
        )
        if run.get("status") in TERMINAL_STATUSES:
            return run


def fetch_dataset_items(dataset_id: str, token: str) -> List[Dict[str, Any]]:
    if not dataset_id:
        raise RuntimeError("Apify run did not return a defaultDatasetId.")
    return apify_request(
        "GET",
        f"/datasets/{dataset_id}/items",
        token=token,
        params={"clean": "true", "format": "json"},
        unwrap=False,
    )


def apify_request(
    method: str,
    path: str,
    token: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, str]] = None,
    unwrap: bool = True,
) -> Any:
    query = parse.urlencode(params or {})
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{query}"

    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    http_request = request.Request(url, method=method, data=data, headers=headers)
    try:
        with request.urlopen(http_request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Apify API request failed: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Apify API request failed: {exc.reason}") from exc

    parsed = json.loads(body)
    return parsed["data"] if unwrap and isinstance(parsed, dict) and "data" in parsed else parsed


def print_run_summary(
    merged_dataset: Dict[str, Any],
    output_path: Path,
    scraped_reviews: List[Dict[str, Any]],
    raw_items: List[Dict[str, Any]],
    projected: Dict[str, Any],
    skipped: bool = False,
) -> None:
    action = "Prepared" if skipped else "Wrote"
    print(f"{action} Apify incremental dataset: {output_path.relative_to(ROOT)}")
    print(f"Raw Apify items: {len(raw_items)}")
    print(f"Matched scraped reviews: {len(scraped_reviews)}")
    print(
        "Projected usage: "
        f"{projected['dailyReviews']} reviews/day, "
        f"{projected['monthlyReviews']} reviews/{projected['billingDays']} days, "
        f"${projected['monthlyCostUsd']:.2f}/month"
    )
    for branch in merged_dataset.get("branches") or []:
        print(
            f"- {branch['id']}: rating {float(branch.get('currentRating') or 0):.1f}, "
            f"{int(float(branch.get('currentReviewsCount') or 0))} total reviews"
        )


def parse_positive_int(value: Any, default: int, name: str) -> int:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number.") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be at least 1.")
    return parsed


def first_number(*values: Any) -> float:
    for value in values:
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def average(values: Iterable[Any]) -> float:
    valid_values = []
    for value in values:
        numeric = first_number(value, 0)
        if numeric > 0:
            valid_values.append(numeric)
    return sum(valid_values) / len(valid_values) if valid_values else 0.0


def round_one_decimal(value: Any) -> float:
    numeric = first_number(value, 0)
    return int((numeric * 10) + 0.5) / 10


def normalize_text(value: Optional[str]) -> str:
    return " ".join(str(value or "").lower().replace("&", "and").replace("-", " ").split())


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise KeyError(f"Missing required environment variable: {name}")
    return value


def env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def render_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True)


if __name__ == "__main__":
    raise SystemExit(main())
