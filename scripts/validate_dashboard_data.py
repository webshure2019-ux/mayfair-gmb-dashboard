#!/usr/bin/env python3
"""Validate the dashboard dataset before it is published."""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "reviews.json"


def main() -> int:
    dataset_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_DATASET
    payload = read_json(dataset_path)
    errors = validate_payload(payload)

    if errors:
        print(f"Dataset validation failed for {dataset_path}:")
        for message in errors:
            print(f"- {message}")
        return 1

    print(f"Dataset validation passed for {dataset_path}")
    print(f"Mode: {payload.get('meta', {}).get('mode', 'unknown')}")
    print(f"Branches: {len(payload.get('branches', []))}")
    print(f"Reviews: {len(payload.get('reviews', []))}")
    return 0


def validate_payload(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    meta = payload.get("meta") or {}
    branches = payload.get("branches") or []
    reviews = payload.get("reviews") or []

    if not isinstance(branches, list) or not branches:
        errors.append("No branches were found in the dataset.")
        return errors

    if not isinstance(reviews, list):
        errors.append("The reviews payload is not a list.")
        return errors

    branch_ids = [branch.get("id") for branch in branches]
    duplicate_branch_ids = [branch_id for branch_id, count in Counter(branch_ids).items() if count > 1]
    if duplicate_branch_ids:
        errors.append(f"Duplicate branch IDs found: {', '.join(sorted(map(str, duplicate_branch_ids)))}")

    branch_lookup = {branch["id"]: branch for branch in branches if branch.get("id")}
    reviews_by_branch: Dict[str, List[Dict[str, Any]]] = {branch_id: [] for branch_id in branch_lookup}
    seen_review_keys: set[str] = set()

    for review in reviews:
        branch_id = review.get("branchId")
        review_id = review.get("id")
        if branch_id not in branch_lookup:
            errors.append(
                f"Review {review_id or '<missing id>'} references unknown branchId {branch_id!r}."
            )
            continue

        review_key = f"{branch_id}::{review_id}"
        if review_key in seen_review_keys:
            errors.append(f"Duplicate review key found: {review_key}")
            continue

        seen_review_keys.add(review_key)
        reviews_by_branch[branch_id].append(review)

    meta_review_count = int(meta.get("reviewCount") or 0)
    if meta_review_count != len(reviews):
        errors.append(
            f"meta.reviewCount is {meta_review_count}, but the dataset contains {len(reviews)} reviews."
        )

    overall_branch_total = 0
    live_mode = meta.get("mode") == "live"

    for branch in branches:
        branch_id = branch.get("id")
        branch_name = branch.get("name") or branch_id or "Unknown branch"
        branch_reviews = reviews_by_branch.get(branch_id, [])
        tracked_count = len(branch_reviews)
        configured_count = int(float(branch.get("currentReviewsCount") or 0))
        overall_branch_total += configured_count

        if configured_count != tracked_count:
            errors.append(
                f"{branch_name}: currentReviewsCount is {configured_count}, but {tracked_count} reviews were matched."
            )

        rounded_average = round_one_decimal(average([review.get("rating") for review in branch_reviews]))
        configured_rating = round_one_decimal(branch.get("currentRating") or 0)
        if tracked_count and configured_rating != rounded_average:
            errors.append(
                f"{branch_name}: currentRating is {configured_rating:.1f}, but matched reviews round to {rounded_average:.1f}."
            )

        if live_mode and tracked_count == 0:
            errors.append(f"{branch_name}: live dataset contains no matched reviews.")

        wrong_names = {
            str(review.get("branchName"))
            for review in branch_reviews
            if str(review.get("branchName") or "").strip() != str(branch.get("name") or "").strip()
        }
        if wrong_names:
            errors.append(
                f"{branch_name}: review branchName values do not match the configured branch name."
            )

    if overall_branch_total != len(reviews):
        errors.append(
            f"The sum of branch currentReviewsCount values is {overall_branch_total}, but the dataset contains {len(reviews)} reviews."
        )

    return errors


def average(values: List[Any]) -> float:
    valid_values = [float(value) for value in values if is_positive_number(value)]
    return sum(valid_values) / len(valid_values) if valid_values else 0.0


def is_positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def round_one_decimal(value: Any) -> float:
    numeric = float(value or 0)
    return math.floor((numeric * 10) + 0.5) / 10


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
