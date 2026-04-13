#!/usr/bin/env python3
"""Fetch Mayfair Gearbox Google review data from Google Business Profile APIs."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from gbp_common import (
    REVIEWS_API_BASE,
    env_flag,
    first_env,
    google_api_request,
    parse_optional_int,
    quote_resource_name,
    read_json,
    refresh_access_token,
    require_env,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]
BRANCHES_PATH = ROOT / "config" / "branches.json"
OUTPUT_PATH = ROOT / "data" / "reviews.json"
RAW_OUTPUT_PATH = ROOT / "data" / "raw" / "gbp-reviews-latest.json"
PREVIEW_OUTPUT_PATH = ROOT / "data" / "preview" / "reviews-preview.json"
PREVIEW_RAW_OUTPUT_PATH = ROOT / "data" / "preview" / "gbp-reviews-preview.json"

GOOGLE_SOURCE = "Google Business Profile API"
DEFAULT_PAGE_SIZE = 50
DEFAULT_TIMEOUT_SECONDS = 120
STAR_RATING_MAP = {
    "ONE": 1,
    "TWO": 2,
    "THREE": 3,
    "FOUR": 4,
    "FIVE": 5,
}


def main() -> int:
    all_branches = read_json(BRANCHES_PATH)
    branches = filter_branches(all_branches)
    preview_mode = env_flag("GBP_PREVIEW_MODE", "APIFY_PREVIEW_MODE")
    skip_write = env_flag("GBP_SKIP_WRITE", "APIFY_SKIP_WRITE")
    dry_run = env_flag("GBP_DRY_RUN", "APIFY_DRY_RUN")
    max_reviews = parse_optional_int(
        first_env("GBP_MAX_REVIEWS", "APIFY_MAX_REVIEWS"),
        "GBP_MAX_REVIEWS",
    )

    ensure_safe_write_selection(
        all_branches=all_branches,
        selected_branches=branches,
        preview_mode=preview_mode,
        dry_run=dry_run,
        max_reviews=max_reviews,
    )
    output_path, raw_output_path = choose_output_paths(preview_mode)
    generated_at = datetime.now(timezone.utc).isoformat()

    if dry_run:
        print_dry_run(
            branches=branches,
            output_path=output_path,
            raw_output_path=raw_output_path,
            preview_mode=preview_mode,
            skip_write=skip_write,
            max_reviews=max_reviews,
        )
        return 0

    ensure_branch_location_names(branches)

    client_id = require_env("GBP_CLIENT_ID")
    client_secret = require_env("GBP_CLIENT_SECRET")
    refresh_token = require_env("GBP_REFRESH_TOKEN")
    timeout_seconds = parse_optional_int(
        first_env("GBP_TIMEOUT_SECONDS"),
        "GBP_TIMEOUT_SECONDS",
    ) or DEFAULT_TIMEOUT_SECONDS

    token_data = refresh_access_token(client_id, client_secret, refresh_token)
    access_token = token_data["access_token"]

    raw_payload, normalized = fetch_and_normalize_dataset(
        branches=branches,
        access_token=access_token,
        generated_at=generated_at,
        timeout_seconds=timeout_seconds,
        preview_mode=preview_mode,
        max_reviews=max_reviews,
    )

    if normalized["meta"].get("reviewCount", 0) == 0:
        print(
            "Google Business Profile returned no reviews for the configured branches. "
            "The dataset was not written to avoid publishing an empty dashboard.",
        )
        print_debug_summary(normalized)
        return 1

    missing_branches = normalized["meta"].get("missingBranchIds") or []
    if missing_branches:
        print(
            "Google Business Profile returned zero matched reviews for one or more configured "
            "branches. The dataset was not written to avoid publishing incomplete branch data.",
        )
        print_debug_summary(normalized)
        return 1

    if skip_write:
        print_run_summary(normalized, output_path, skipped=True)
        return 0

    write_json(raw_output_path, raw_payload)
    write_json(output_path, normalized)
    print_run_summary(normalized, output_path)
    return 0


def fetch_and_normalize_dataset(
    branches: List[Dict[str, Any]],
    access_token: str,
    generated_at: str,
    timeout_seconds: int,
    preview_mode: bool,
    max_reviews: Optional[int],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    raw_branch_payloads: List[Dict[str, Any]] = []
    normalized_branches: List[Dict[str, Any]] = []
    normalized_reviews: List[Dict[str, Any]] = []

    for branch in branches:
        branch_payload = fetch_reviews_for_branch(
            branch=branch,
            access_token=access_token,
            timeout_seconds=timeout_seconds,
            max_reviews=max_reviews,
            generated_at=generated_at,
        )
        raw_branch_payloads.append(branch_payload)
        normalized_branches.append(branch_payload["branch"])
        normalized_reviews.extend(branch_payload["reviews"])

    deduped_reviews = deduplicate_reviews(normalized_reviews)
    deduped_reviews.sort(
        key=lambda review: review.get("publishedAt") or review.get("updatedAt") or review.get("scrapedAt") or "",
        reverse=True,
    )
    matched_review_counts = Counter(review["branchId"] for review in deduped_reviews)
    branch_match_summary = [
        {
            "id": branch["id"],
            "matchedReviews": int(matched_review_counts.get(branch["id"], 0)),
        }
        for branch in normalized_branches
    ]
    missing_branch_ids = [
        summary["id"]
        for summary in branch_match_summary
        if summary["matchedReviews"] == 0
    ]

    meta = {
        "mode": "preview" if preview_mode else "live",
        "generatedAt": generated_at,
        "timezone": "Africa/Johannesburg",
        "source": GOOGLE_SOURCE,
        "actorId": None,
        "actorRunId": None,
        "reviewCount": len(deduped_reviews),
        "branchMatchSummary": branch_match_summary,
        "missingBranchIds": missing_branch_ids,
        "selectedBranchIds": [branch["id"] for branch in branches],
        "sampled": bool(max_reviews),
        "maxReviewsPerBranch": max_reviews,
        "oauthScope": "https://www.googleapis.com/auth/business.manage",
    }

    raw_payload = {
        "meta": {
            **meta,
            "accessTokenType": token_summary(),
            "rawBranchCount": len(raw_branch_payloads),
        },
        "branches": [item["raw"] for item in raw_branch_payloads],
    }

    normalized = {
        "meta": meta,
        "branches": normalized_branches,
        "reviews": deduped_reviews,
    }

    return raw_payload, normalized


def fetch_reviews_for_branch(
    branch: Dict[str, Any],
    access_token: str,
    timeout_seconds: int,
    max_reviews: Optional[int],
    generated_at: str,
) -> Dict[str, Any]:
    location_name = str(branch.get("googleLocationName") or "").strip()
    url = f"{REVIEWS_API_BASE}/{quote_resource_name(location_name)}/reviews"
    reviews: List[Dict[str, Any]] = []
    page_token = ""
    page_count = 0
    total_review_count = 0
    average_rating = 0.0

    while True:
        params = {
            "pageSize": str(DEFAULT_PAGE_SIZE),
            "orderBy": "updateTime desc",
        }
        if page_token:
            params["pageToken"] = page_token

        response = google_api_request(
            "GET",
            url,
            access_token=access_token,
            params=params,
            timeout=timeout_seconds,
        )
        page_count += 1
        total_review_count = int(response.get("totalReviewCount") or total_review_count or 0)
        average_rating = round_one_decimal(response.get("averageRating") or average_rating or 0)

        for item in response.get("reviews") or []:
            normalized_review = normalize_review(
                item=item,
                branch=branch,
                fetched_at=generated_at,
            )
            if normalized_review:
                reviews.append(normalized_review)
            if max_reviews is not None and len(reviews) >= max_reviews:
                reviews = reviews[:max_reviews]
                page_token = ""
                break

        if max_reviews is not None and len(reviews) >= max_reviews:
            break

        page_token = str(response.get("nextPageToken") or "").strip()
        if not page_token:
            break

    normalized_branch = {
        **branch,
        "currentReviewsCount": total_review_count or len(reviews),
        "currentRating": average_rating or round_one_decimal(average([review.get("rating") for review in reviews])),
        "placeUrl": branch.get("profileUrl") or branch.get("mapsSearchUrl"),
        "fid": branch.get("fid"),
        "imageUrl": branch.get("imageUrl"),
    }

    raw_branch = {
        "branchId": branch["id"],
        "branchName": branch["name"],
        "googleLocationName": location_name,
        "currentReviewsCount": normalized_branch["currentReviewsCount"],
        "currentRating": normalized_branch["currentRating"],
        "pageCount": page_count,
        "sampled": bool(max_reviews),
        "reviews": reviews,
    }

    return {
        "branch": normalized_branch,
        "reviews": reviews,
        "raw": raw_branch,
    }


def normalize_review(
    item: Dict[str, Any],
    branch: Dict[str, Any],
    fetched_at: str,
) -> Optional[Dict[str, Any]]:
    review_id = str(item.get("reviewId") or "").strip()
    published_at = item.get("createTime")
    updated_at = item.get("updateTime") or published_at
    rating = star_rating_to_int(item.get("starRating"))

    if not review_id or not published_at or rating <= 0:
        return None

    reviewer = item.get("reviewer") or {}
    owner_reply = item.get("reviewReply") or {}
    owner_response_date = owner_reply.get("updateTime")

    return {
        "id": review_id,
        "branchId": branch["id"],
        "branchName": branch["name"],
        "reviewerName": reviewer.get("displayName") or "Anonymous reviewer",
        "reviewerUrl": None,
        "reviewerProfilePhotoUrl": reviewer.get("profilePhotoUrl"),
        "reviewerReviewCount": 0,
        "isLocalGuide": False,
        "rating": rating,
        "comment": item.get("comment") or "",
        "commentTranslated": "",
        "publishedAt": published_at,
        "updatedAt": updated_at,
        "publishedLabel": "",
        "reviewUrl": None,
        "reviewSource": "Google Business Profile review",
        "ownerResponseText": owner_reply.get("comment") or "",
        "ownerResponseDate": owner_response_date,
        "ownerResponseUpdatedAt": owner_response_date,
        "reviewImageUrls": [],
        "language": None,
        "translatedLanguage": None,
        "scrapedAt": fetched_at,
        "placeId": branch.get("placeId"),
        "cid": branch.get("cid"),
        "fid": branch.get("fid"),
        "placeUrl": branch.get("profileUrl") or branch.get("mapsSearchUrl"),
        "title": branch.get("name"),
    }


def filter_branches(branches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected_ids = [
        branch_id.strip()
        for branch_id in first_env("GBP_BRANCH_IDS", "APIFY_BRANCH_IDS").split(",")
        if branch_id.strip()
    ]

    if not selected_ids:
        return branches

    branch_lookup = {branch["id"]: branch for branch in branches}
    missing_ids = [branch_id for branch_id in selected_ids if branch_id not in branch_lookup]

    if missing_ids:
        raise KeyError(
            f"Unknown branch id(s) in GBP_BRANCH_IDS: {', '.join(sorted(missing_ids))}"
        )

    return [branch_lookup[branch_id] for branch_id in selected_ids]


def ensure_safe_write_selection(
    all_branches: List[Dict[str, Any]],
    selected_branches: List[Dict[str, Any]],
    preview_mode: bool,
    dry_run: bool,
    max_reviews: Optional[int],
) -> None:
    if preview_mode or dry_run:
        return

    if len(selected_branches) != len(all_branches):
        raise RuntimeError(
            "Publishing a live dataset with GBP_BRANCH_IDS is blocked because it would "
            "replace the dashboard with partial branch coverage. Use preview mode instead."
        )

    if max_reviews is not None:
        raise RuntimeError(
            "Publishing a live dataset with GBP_MAX_REVIEWS is blocked because it would "
            "replace the dashboard with a sampled dataset. Use preview mode instead."
        )


def ensure_branch_location_names(branches: Iterable[Dict[str, Any]]) -> None:
    missing = [branch["id"] for branch in branches if not str(branch.get("googleLocationName") or "").strip()]
    if missing:
        raise RuntimeError(
            "The following branches are missing googleLocationName in config/branches.json: "
            + ", ".join(sorted(missing))
        )


def choose_output_paths(preview_mode: bool) -> tuple[Path, Path]:
    if preview_mode:
        return PREVIEW_OUTPUT_PATH, PREVIEW_RAW_OUTPUT_PATH
    return OUTPUT_PATH, RAW_OUTPUT_PATH


def print_dry_run(
    branches: List[Dict[str, Any]],
    output_path: Path,
    raw_output_path: Path,
    preview_mode: bool,
    skip_write: bool,
    max_reviews: Optional[int],
) -> None:
    print(
        render_json(
            {
                "mode": "preview" if preview_mode else "live",
                "skipWrite": skip_write,
                "maxReviewsPerBranch": max_reviews,
                "outputPath": str(output_path.relative_to(ROOT)),
                "rawOutputPath": str(raw_output_path.relative_to(ROOT)),
                "selectedBranches": [
                    {
                        "id": branch["id"],
                        "name": branch["name"],
                        "googleLocationName": branch.get("googleLocationName"),
                        "googleLocationNameConfigured": bool(str(branch.get("googleLocationName") or "").strip()),
                    }
                    for branch in branches
                ],
            }
        )
    )


def print_run_summary(
    normalized: Dict[str, Any],
    output_path: Path,
    skipped: bool = False,
) -> None:
    action = "Prepared" if skipped else "Wrote"
    print(
        f"{action} {len(normalized['reviews'])} normalized reviews "
        f"for {len(normalized['branches'])} branches"
    )
    print(f"Target dataset: {output_path.relative_to(ROOT)}")
    print("Branch summary:")

    for branch in normalized["branches"]:
        print(
            f"- {branch['id']}: rating {branch.get('currentRating', 0):.1f}, "
            f"{int(branch.get('currentReviewsCount', 0))} total reviews"
        )

    print_debug_summary(normalized)


def print_debug_summary(normalized: Dict[str, Any]) -> None:
    meta = normalized.get("meta", {})
    print(
        f"Matched reviews: {int(meta.get('reviewCount', 0))} | "
        f"Sampled: {bool(meta.get('sampled'))}"
    )
    branch_summaries = meta.get("branchMatchSummary") or []
    if branch_summaries:
        print("Matched review count by branch:")
        for summary in branch_summaries:
            print(
                f"- {summary['id']}: {int(summary.get('matchedReviews', 0))} matched reviews"
            )
    missing_branches = meta.get("missingBranchIds") or []
    if missing_branches:
        print(f"Missing branches: {', '.join(missing_branches)}")


def deduplicate_reviews(reviews: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}

    for review in reviews:
        key = f"{review['branchId']}::{review['id']}"
        seen[key] = review

    return list(seen.values())


def star_rating_to_int(value: Any) -> int:
    if isinstance(value, str):
        return STAR_RATING_MAP.get(value.strip().upper(), 0)

    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 0

    return numeric if 1 <= numeric <= 5 else 0


def average(values: Iterable[Any]) -> float:
    valid_values = []
    for value in values:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            valid_values.append(numeric)
    return sum(valid_values) / len(valid_values) if valid_values else 0.0


def round_one_decimal(value: Any) -> float:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        numeric = 0.0
    return int((numeric * 10) + 0.5) / 10


def render_json(payload: Dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=True)


def token_summary() -> str:
    return "oauth_refresh_token"


if __name__ == "__main__":
    raise SystemExit(main())
