#!/usr/bin/env python3
"""Fetch Mayfair Gearbox Google review data from Apify and write dashboard JSON."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[1]
BRANCHES_PATH = ROOT / "config" / "branches.json"
OUTPUT_PATH = ROOT / "data" / "reviews.json"
RAW_OUTPUT_PATH = ROOT / "data" / "raw" / "apify-reviews-latest.json"
PREVIEW_OUTPUT_PATH = ROOT / "data" / "preview" / "reviews-preview.json"
PREVIEW_RAW_OUTPUT_PATH = ROOT / "data" / "preview" / "apify-reviews-preview.json"
API_BASE = "https://api.apify.com/v2"
DEFAULT_ACTOR = "compass/google-maps-reviews-scraper"
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}


def main() -> int:
    token = os.getenv("APIFY_API_TOKEN")
    actor_id = os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR)
    timeout_seconds = int(os.getenv("APIFY_TIMEOUT_SECONDS", "1800"))
    dry_run = env_flag("APIFY_DRY_RUN")
    skip_write = env_flag("APIFY_SKIP_WRITE")
    preview_mode = env_flag("APIFY_PREVIEW_MODE")

    branches = filter_branches(read_json(BRANCHES_PATH))
    run_input = build_actor_input(branches)

    if dry_run:
        print(json.dumps({
            "actorId": actor_id,
            "branchIds": [branch["id"] for branch in branches],
            "runInput": run_input,
        }, indent=2))
        return 0

    if not token:
        print("APIFY_API_TOKEN is required to fetch live review data.", file=sys.stderr)
        return 1

    run = start_run(actor_id, token, run_input)
    run_id = run["id"]
    run = wait_for_run(run_id, token, timeout_seconds)

    if run.get("status") != "SUCCEEDED":
        print(
            f"Apify run {run_id} finished with status {run.get('status')}.",
            file=sys.stderr,
        )
        return 1

    dataset_id = run.get("defaultDatasetId")
    items = fetch_dataset_items(dataset_id, token)

    normalized = normalize_dataset(branches, items, actor_id, run_id)
    output_path, raw_output_path = choose_output_paths(preview_mode)

    if normalized["meta"].get("reviewCount", 0) == 0:
        print(
            "Apify returned no matched reviews for the configured branches. "
            "The dataset was not written to avoid publishing an empty dashboard.",
            file=sys.stderr,
        )
        print_debug_summary(normalized)
        return 1

    if skip_write:
        print_run_summary(normalized, output_path, skipped=True)
        return 0

    write_json(raw_output_path, items)
    write_json(output_path, normalized)

    print_run_summary(normalized, output_path)
    return 0


def build_actor_input(branches: List[Dict[str, Any]]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "startUrls": [{"url": branch["mapsSearchUrl"]} for branch in branches],
        "reviewsSort": os.getenv("APIFY_REVIEWS_SORT", "newest"),
        "language": os.getenv("APIFY_LANGUAGE", "en"),
    }

    max_reviews = os.getenv("APIFY_MAX_REVIEWS")
    if max_reviews:
        payload["maxReviews"] = int(max_reviews)

    reviews_start_date = os.getenv("APIFY_REVIEWS_START_DATE")
    if reviews_start_date:
        payload["reviewsStartDate"] = reviews_start_date

    return payload


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
        raise KeyError(
            f"Unknown branch id(s) in APIFY_BRANCH_IDS: {', '.join(sorted(missing_ids))}"
        )

    return [branch_lookup[branch_id] for branch_id in selected_ids]


def choose_output_paths(preview_mode: bool) -> tuple[Path, Path]:
    if preview_mode:
        return PREVIEW_OUTPUT_PATH, PREVIEW_RAW_OUTPUT_PATH
    return OUTPUT_PATH, RAW_OUTPUT_PATH


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
        f"Raw items fetched: {int(meta.get('rawItemCount', 0))} | "
        f"Matched reviews: {int(meta.get('reviewCount', 0))} | "
        f"Unmatched items: {int(meta.get('unmatchedItemCount', 0))}"
    )
    unmatched_samples = meta.get("unmatchedSamples") or []
    if unmatched_samples:
        print("Unmatched sample items:")
        for sample in unmatched_samples:
            print(
                "- "
                f"title={sample.get('title')!r}, "
                f"cid={sample.get('cid')!r}, "
                f"placeId={sample.get('placeId')!r}"
            )


def start_run(actor_id: str, token: str, run_input: Dict[str, Any]) -> Dict[str, Any]:
    actor_ref = actor_id.replace("/", "~")
    return apify_request(
        method="POST",
        path=f"/acts/{actor_ref}/runs",
        token=token,
        payload=run_input,
    )


def wait_for_run(run_id: str, token: str, timeout_seconds: int) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    poll_window = min(60, timeout_seconds)

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(
                f"Timed out waiting for Apify run {run_id} after {timeout_seconds} seconds."
            )

        response = apify_request(
            method="GET",
            path=f"/actor-runs/{run_id}",
            token=token,
            params={"waitForFinish": str(min(poll_window, max(1, int(remaining))))},
        )
        run = response

        if run.get("status") in TERMINAL_STATUSES:
            return run


def fetch_dataset_items(dataset_id: str, token: str) -> List[Dict[str, Any]]:
    return apify_request(
        method="GET",
        path=f"/datasets/{dataset_id}/items",
        token=token,
        params={"clean": "true", "format": "json"},
        unwrap=False,
    )


def normalize_dataset(
    branches: List[Dict[str, Any]],
    items: Iterable[Dict[str, Any]],
    actor_id: str,
    run_id: str,
) -> Dict[str, Any]:
    items = list(items)
    branch_lookup = {branch["id"]: {**branch} for branch in branches}
    normalized_reviews: List[Dict[str, Any]] = []
    unmatched_items: List[Dict[str, Any]] = []

    for branch in branch_lookup.values():
        branch["currentReviewsCount"] = 0
        branch["currentRating"] = 0
        branch["placeUrl"] = branch.get("mapsSearchUrl")
        branch["placeId"] = None
        branch["fid"] = None
        branch["imageUrl"] = None

    for item in items:
        branch = match_branch(item, branch_lookup.values())
        if not branch:
            unmatched_items.append(item)
            continue

        branch["currentReviewsCount"] = first_number(
            item.get("reviewsCount"),
            branch["currentReviewsCount"],
        )
        branch["currentRating"] = first_number(
            item.get("totalScore"),
            branch["currentRating"],
        )
        branch["placeUrl"] = item.get("url") or branch["placeUrl"]
        branch["placeId"] = item.get("placeId") or branch["placeId"]
        branch["fid"] = item.get("fid") or branch["fid"]
        branch["imageUrl"] = item.get("imageUrl") or branch["imageUrl"]

        review = normalize_review(item, branch)
        if review:
            normalized_reviews.append(review)

    deduped_reviews = deduplicate_reviews(normalized_reviews)
    deduped_reviews.sort(
        key=lambda review: review.get("publishedAt") or review.get("scrapedAt") or "",
        reverse=True,
    )

    generated_at = datetime.now(timezone.utc).isoformat()

    return {
        "meta": {
            "mode": "live",
            "generatedAt": generated_at,
            "timezone": "Africa/Johannesburg",
            "source": "Apify",
            "actorId": actor_id,
            "actorRunId": run_id,
            "reviewCount": len(deduped_reviews),
            "rawItemCount": len(items),
            "unmatchedItemCount": len(unmatched_items),
            "unmatchedSamples": [
                {
                    "title": item.get("title"),
                    "cid": item.get("cid"),
                    "placeId": item.get("placeId"),
                }
                for item in unmatched_items[:5]
            ],
        },
        "branches": list(branch_lookup.values()),
        "reviews": deduped_reviews,
    }


def normalize_review(item: Dict[str, Any], branch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    review_id = item.get("reviewId")
    published_at = item.get("publishedAtDate") or item.get("scrapedAt")
    rating = first_number(item.get("stars"), item.get("rating"), 0)

    if not review_id or not published_at or not rating:
        return None

    return {
        "id": review_id,
        "branchId": branch["id"],
        "branchName": branch["name"],
        "reviewerName": item.get("name") or "Anonymous reviewer",
        "reviewerUrl": item.get("reviewerUrl"),
        "reviewerReviewCount": first_number(item.get("reviewerNumberOfReviews"), 0),
        "isLocalGuide": bool(item.get("isLocalGuide")),
        "rating": int(rating),
        "comment": item.get("text") or "",
        "commentTranslated": item.get("textTranslated") or "",
        "publishedAt": published_at,
        "publishedLabel": item.get("publishAt"),
        "reviewUrl": item.get("reviewUrl"),
        "reviewSource": item.get("reviewOrigin") or "Google",
        "ownerResponseText": item.get("responseFromOwnerText") or "",
        "ownerResponseDate": item.get("responseFromOwnerDate"),
        "reviewImageUrls": item.get("reviewImageUrls") or [],
        "language": item.get("originalLanguage") or item.get("language"),
        "translatedLanguage": item.get("translatedLanguage"),
        "scrapedAt": item.get("scrapedAt"),
        "placeId": item.get("placeId"),
        "cid": item.get("cid"),
        "fid": item.get("fid"),
        "placeUrl": item.get("url"),
        "title": item.get("title"),
    }


def match_branch(
    item: Dict[str, Any], branches: Iterable[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    place_id = str(item.get("placeId") or "").strip()
    cid = str(item.get("cid") or "").strip()
    title = normalize_text(item.get("title"))
    branch_list = list(branches)

    for branch in branch_list:
        if place_id and place_id == str(branch.get("placeId") or "").strip():
            return branch

    for branch in branch_list:
        if cid and cid == str(branch.get("cid")):
            return branch

    if not title:
        return None

    for branch in branch_list:
        candidates = branch_candidates(branch)
        if any(candidate and candidate == title for candidate in candidates):
            return branch

    for branch in branch_list:
        candidates = branch_candidates(branch)
        if any(
            candidate
            and (title.startswith(candidate) or candidate.startswith(title))
            for candidate in candidates
        ):
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


def deduplicate_reviews(reviews: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}

    for review in reviews:
        key = f"{review['branchId']}::{review['id']}"
        seen[key] = review

    return list(seen.values())


def normalize_text(value: Optional[str]) -> str:
    return " ".join(str(value or "").lower().replace("&", "and").split())


def first_number(*values: Any) -> float:
    for value in values:
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


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

    parsed = json.loads(body)
    return parsed["data"] if unwrap and isinstance(parsed, dict) and "data" in parsed else parsed


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
