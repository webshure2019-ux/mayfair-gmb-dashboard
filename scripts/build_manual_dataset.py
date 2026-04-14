#!/usr/bin/env python3
"""Build the deploy dataset from a frozen live snapshot plus manual review additions."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from gbp_common import read_json, write_json


ROOT = Path(__file__).resolve().parents[1]
BRANCHES_PATH = ROOT / "config" / "branches.json"
BASE_DATASET_PATH = ROOT / "data" / "manual" / "base-reviews.json"
MANUAL_ADDITIONS_PATH = ROOT / "data" / "manual" / "manual-review-additions.csv"
MANUAL_REMOVALS_PATH = ROOT / "data" / "manual" / "manual-review-removals.csv"
OUTPUT_PATH = ROOT / "data" / "reviews.json"


def main() -> int:
    branches = read_json(BRANCHES_PATH)
    base_dataset = read_json(BASE_DATASET_PATH)
    additions = load_manual_additions(MANUAL_ADDITIONS_PATH, branches, base_dataset)
    removals = load_manual_removals(MANUAL_REMOVALS_PATH, branches)
    merged = build_dataset(branches, base_dataset, additions, removals)
    write_json(OUTPUT_PATH, merged)

    print(
        f"Wrote manual dataset with {len(merged['reviews'])} reviews "
        f"({len(additions)} manual additions, {len(removals)} manual removals) "
        f"to {OUTPUT_PATH.relative_to(ROOT)}"
    )
    for branch in merged["branches"]:
        print(
            f"- {branch['id']}: rating {float(branch.get('currentRating') or 0):.1f}, "
            f"{int(float(branch.get('currentReviewsCount') or 0))} total reviews"
        )
    return 0


def build_dataset(
    configured_branches: List[Dict[str, Any]],
    base_dataset: Dict[str, Any],
    manual_additions: List[Dict[str, Any]],
    manual_removals: List[Dict[str, Any]],
) -> Dict[str, Any]:
    base_branches_by_id = {branch["id"]: branch for branch in base_dataset.get("branches") or []}
    base_reviews = base_dataset.get("reviews") or []
    merged_reviews_by_key: Dict[str, Dict[str, Any]] = {}
    removed_review_keys = {removal["reviewKey"] for removal in manual_removals}

    for review in base_reviews:
        key = review_key(review)
        if key in removed_review_keys:
            continue
        merged_reviews_by_key[key] = review

    for review in manual_additions:
        key = review_key(review)
        if key in removed_review_keys:
            continue
        merged_reviews_by_key[key] = review

    merged_reviews = list(merged_reviews_by_key.values())
    merged_reviews.sort(
        key=lambda review: review.get("publishedAt") or review.get("updatedAt") or review.get("scrapedAt") or "",
        reverse=True,
    )

    reviews_by_branch: Dict[str, List[Dict[str, Any]]] = {branch["id"]: [] for branch in configured_branches}
    for review in merged_reviews:
        branch_id = review.get("branchId")
        if branch_id in reviews_by_branch:
            reviews_by_branch[branch_id].append(review)

    merged_branches: List[Dict[str, Any]] = []
    for branch in configured_branches:
        branch_id = branch["id"]
        base_branch = base_branches_by_id.get(branch_id, {})
        branch_reviews = reviews_by_branch.get(branch_id, [])
        merged_branch = {
            **base_branch,
            **branch,
            "currentReviewsCount": len(branch_reviews),
            "currentRating": round_one_decimal(average(review.get("rating") for review in branch_reviews)),
            "placeUrl": base_branch.get("placeUrl") or branch.get("mapsSearchUrl") or branch.get("profileUrl"),
            "fid": base_branch.get("fid"),
            "imageUrl": base_branch.get("imageUrl"),
        }
        merged_branches.append(merged_branch)

    manual_branch_counts = {}
    for review in manual_additions:
        manual_branch_counts[review["branchId"]] = manual_branch_counts.get(review["branchId"], 0) + 1

    manual_removed_branch_counts = {}
    for removal in manual_removals:
        branch_id = removal["branchId"]
        manual_removed_branch_counts[branch_id] = manual_removed_branch_counts.get(branch_id, 0) + 1

    meta = {
        "mode": "manual",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "timezone": base_dataset.get("meta", {}).get("timezone") or "Africa/Johannesburg",
        "source": "Manual update workflow",
        "reviewCount": len(merged_reviews),
        "manualReviewCount": len(manual_additions),
        "manualBranchCounts": manual_branch_counts,
        "manualRemovalCount": len(manual_removals),
        "manualRemovedBranchCounts": manual_removed_branch_counts,
        "baseGeneratedAt": base_dataset.get("meta", {}).get("generatedAt"),
        "baseSource": base_dataset.get("meta", {}).get("source"),
        "actorId": None,
        "actorRunId": None,
    }

    return {
        "meta": meta,
        "branches": merged_branches,
        "reviews": merged_reviews,
    }


def load_manual_additions(
    csv_path: Path,
    branches: List[Dict[str, Any]],
    base_dataset: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not csv_path.exists():
        return []

    branch_lookup = {branch["id"]: branch for branch in branches}
    base_branches_by_id = {branch["id"]: branch for branch in base_dataset.get("branches") or []}
    additions: List[Dict[str, Any]] = []
    seen_csv_keys: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            if not has_manual_content(row):
                continue

            branch_id = clean(row.get("branch_id"))
            if branch_id not in branch_lookup:
                raise ValueError(
                    f"{csv_path.name} row {row_number}: unknown branch_id {branch_id!r}. "
                    f"Use one of: {', '.join(sorted(branch_lookup))}"
                )

            rating = parse_rating(row.get("rating"), csv_path, row_number)
            published_at = normalize_datetime(row.get("published_at"), csv_path, row_number)
            reviewer_name = clean(row.get("reviewer_name")) or "Anonymous reviewer"
            comment = clean(row.get("comment"))
            owner_response_text = clean(row.get("owner_response_text"))
            owner_response_date = normalize_datetime(
                row.get("owner_response_date"),
                csv_path,
                row_number,
                required=False,
            )
            review_id = clean(row.get("review_id")) or generate_manual_review_id(
                branch_id=branch_id,
                reviewer_name=reviewer_name,
                rating=rating,
                published_at=published_at,
                comment=comment,
            )
            csv_key = f"{branch_id}::{review_id}"
            if csv_key in seen_csv_keys:
                raise ValueError(
                    f"{csv_path.name} row {row_number}: duplicate review_id {review_id!r} for branch {branch_id!r}."
                )
            seen_csv_keys.add(csv_key)

            branch = branch_lookup[branch_id]
            base_branch = base_branches_by_id.get(branch_id, {})
            additions.append(
                {
                    "id": review_id,
                    "branchId": branch_id,
                    "branchName": branch["name"],
                    "reviewerName": reviewer_name,
                    "reviewerUrl": clean(row.get("reviewer_url")) or None,
                    "reviewerReviewCount": parse_optional_int(row.get("reviewer_review_count")),
                    "isLocalGuide": parse_optional_bool(row.get("is_local_guide")),
                    "rating": rating,
                    "comment": comment,
                    "commentTranslated": "",
                    "publishedAt": published_at,
                    "updatedAt": published_at,
                    "publishedLabel": "",
                    "reviewUrl": clean(row.get("review_url")) or None,
                    "reviewSource": "Manual update",
                    "ownerResponseText": owner_response_text,
                    "ownerResponseDate": owner_response_date,
                    "ownerResponseUpdatedAt": owner_response_date,
                    "reviewImageUrls": [],
                    "language": clean(row.get("language")) or "en",
                    "translatedLanguage": None,
                    "scrapedAt": datetime.now(timezone.utc).isoformat(),
                    "placeId": branch.get("placeId"),
                    "cid": branch.get("cid"),
                    "fid": base_branch.get("fid"),
                    "placeUrl": base_branch.get("placeUrl") or branch.get("mapsSearchUrl") or branch.get("profileUrl"),
                    "title": branch["name"],
                }
            )

    return additions


def load_manual_removals(
    csv_path: Path,
    branches: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not csv_path.exists():
        return []

    branch_lookup = {branch["id"]: branch for branch in branches}
    removals: List[Dict[str, Any]] = []
    seen_review_keys: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            if not has_manual_content(row):
                continue

            branch_id = clean(row.get("branch_id"))
            if branch_id not in branch_lookup:
                raise ValueError(
                    f"{csv_path.name} row {row_number}: unknown branch_id {branch_id!r}. "
                    f"Use one of: {', '.join(sorted(branch_lookup))}"
                )

            review_id = clean(row.get("review_id"))
            if not review_id:
                raise ValueError(f"{csv_path.name} row {row_number}: review_id is required.")

            review_key_value = f"{branch_id}::{review_id}"
            if review_key_value in seen_review_keys:
                raise ValueError(
                    f"{csv_path.name} row {row_number}: duplicate removal for review_id {review_id!r}."
                )
            seen_review_keys.add(review_key_value)

            removals.append(
                {
                    "branchId": branch_id,
                    "reviewId": review_id,
                    "reviewKey": review_key_value,
                    "reviewerName": clean(row.get("reviewer_name")),
                    "publishedAt": clean(row.get("published_at")),
                    "reason": clean(row.get("reason")),
                }
            )

    return removals


def has_manual_content(row: Dict[str, Any]) -> bool:
    return any(clean(value) for value in row.values())


def parse_rating(value: Any, csv_path: Path, row_number: int) -> int:
    try:
        rating = int(str(value or "").strip())
    except ValueError as exc:
        raise ValueError(f"{csv_path.name} row {row_number}: rating must be a whole number from 1 to 5.") from exc

    if rating < 1 or rating > 5:
        raise ValueError(f"{csv_path.name} row {row_number}: rating must be between 1 and 5.")
    return rating


def normalize_datetime(
    value: Any,
    csv_path: Path,
    row_number: int,
    required: bool = True,
) -> Optional[str]:
    text = clean(value)
    if not text:
        if required:
            raise ValueError(f"{csv_path.name} row {row_number}: published_at is required.")
        return None

    known_formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M",
        "%d %b %Y",
        "%d %b %Y %H:%M",
    ]

    for date_format in known_formats:
        try:
            parsed = datetime.strptime(text, date_format)
            if parsed.tzinfo is None:
                if len(text) <= 10:
                    parsed = parsed.replace(hour=12, minute=0, second=0)
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue

    raise ValueError(
        f"{csv_path.name} row {row_number}: could not understand date {text!r}. "
        "Use YYYY-MM-DD or YYYY-MM-DD HH:MM."
    )


def generate_manual_review_id(
    branch_id: str,
    reviewer_name: str,
    rating: int,
    published_at: str,
    comment: str,
) -> str:
    signature = "|".join([branch_id, reviewer_name, str(rating), published_at, comment.strip()])
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]
    return f"manual-{digest}"


def parse_optional_int(value: Any) -> int:
    text = clean(value)
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def parse_optional_bool(value: Any) -> bool:
    return clean(value).lower() in {"1", "true", "yes", "y"}


def clean(value: Any) -> str:
    return str(value or "").strip()


def review_key(review: Dict[str, Any]) -> str:
    return f"{review.get('branchId')}::{review.get('id')}"


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


def round_one_decimal(value: float) -> float:
    return int((float(value or 0) * 10) + 0.5) / 10


if __name__ == "__main__":
    raise SystemExit(main())
