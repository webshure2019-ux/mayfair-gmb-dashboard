#!/usr/bin/env python3
"""Generate demo review data so the dashboard has a working preview out of the box."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRANCHES_PATH = ROOT / "config" / "branches.json"
OUTPUT_PATH = ROOT / "data" / "reviews.json"


def main() -> None:
    branches = json.loads(BRANCHES_PATH.read_text(encoding="utf-8"))
    branches_by_id = {branch["id"]: {**branch} for branch in branches}

    sample_reviews = [
        review("jhb-auto", branches_by_id["jhb-auto"]["name"], "R1", "Thabo Mokoena", 5, "2026-03-24T06:42:00Z", "Excellent service and the gearbox was sorted quicker than expected.", is_local_guide=True, owner_response_text="Thank you for trusting Mayfair Gearbox with your vehicle."),
        review("jhb-auto", branches_by_id["jhb-auto"]["name"], "R2", "Jason Reid", 4, "2026-03-17T13:18:00Z", "Helpful team and clear communication throughout the repair.", is_local_guide=True),
        review("jhb-auto", branches_by_id["jhb-auto"]["name"], "R3", "Ayanda Sithole", 5, "2026-02-27T09:50:00Z", "Car shifts smoothly again. Very professional from start to finish.", owner_response_text="We appreciate the review and are glad the repair went well."),
        review("jhb-auto", branches_by_id["jhb-auto"]["name"], "R4", "Lerato K", 3, "2026-01-14T10:05:00Z", "Turnaround took longer than I hoped, but the repair fixed the issue."),
        review("germiston-commercial", branches_by_id["germiston-commercial"]["name"], "R5", "Mpho Logistics", 5, "2026-03-22T07:10:00Z", "Truck was back on the road fast and the team kept us updated.", owner_response_text="Thanks for the great feedback from your fleet team."),
        review("germiston-commercial", branches_by_id["germiston-commercial"]["name"], "R6", "Kabelo N", 4, "2026-03-09T12:00:00Z", "Good commercial gearbox specialists with decent turnaround.", is_local_guide=True),
        review("germiston-commercial", branches_by_id["germiston-commercial"]["name"], "R7", "Fleet Ops SA", 5, "2026-02-11T15:25:00Z", "Solved a recurring gearbox issue our previous workshop could not fix.", owner_response_text="Thank you for the opportunity to get the truck back on the road."),
        review("germiston-commercial", branches_by_id["germiston-commercial"]["name"], "R8", "Michael W", 2, "2025-12-19T08:30:00Z", "Repair was done but there were delays around collection."),
        review("pretoria-manual-auto", branches_by_id["pretoria-manual-auto"]["name"], "R9", "Neo M", 5, "2026-03-18T11:45:00Z", "Friendly staff and the vehicle drives perfectly now.", owner_response_text="Thank you for the Pretoria branch review."),
        review("pretoria-manual-auto", branches_by_id["pretoria-manual-auto"]["name"], "R10", "Sipho Dlamini", 5, "2026-03-03T09:15:00Z", "Honest advice and no unnecessary upselling.", is_local_guide=True, owner_response_text="We value your feedback and your trust."),
        review("pretoria-manual-auto", branches_by_id["pretoria-manual-auto"]["name"], "R11", "Antonette V", 4, "2026-02-05T16:35:00Z", "Solid workmanship. They explained the problem in plain language."),
        review("pretoria-manual-auto", branches_by_id["pretoria-manual-auto"]["name"], "R12", "Jabu P", 4, "2026-01-23T10:20:00Z", "Good experience overall and the pricing felt fair.", owner_response_text="Thank you for taking the time to review us."),
        review("jhb-manual", branches_by_id["jhb-manual"]["name"], "R13", "Sanele M", 5, "2026-03-20T08:40:00Z", "Manual gearbox repair was done properly and the noise is gone."),
        review("jhb-manual", branches_by_id["jhb-manual"]["name"], "R14", "Karen Jacobs", 4, "2026-03-06T13:50:00Z", "Very neat workshop and excellent customer service.", is_local_guide=True),
        review("jhb-manual", branches_by_id["jhb-manual"]["name"], "R15", "Bradley N", 4, "2026-02-15T09:05:00Z", "Good value and the team delivered when promised.", owner_response_text="Thank you for the review and support."),
        review("jhb-manual", branches_by_id["jhb-manual"]["name"], "R16", "Themba L", 1, "2025-11-29T14:00:00Z", "Communication around progress could have been much better."),
    ]

    for branch in branches_by_id.values():
        branch_reviews = [item for item in sample_reviews if item["branchId"] == branch["id"]]
        branch["currentReviewsCount"] = len(branch_reviews)
        branch["currentRating"] = round(
            sum(item["rating"] for item in branch_reviews) / len(branch_reviews), 1
        )
        branch["placeUrl"] = branch["mapsSearchUrl"]
        branch["placeId"] = None
        branch["fid"] = None
        branch["imageUrl"] = None

    payload = {
        "meta": {
            "mode": "demo",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "timezone": "Africa/Johannesburg",
            "source": "Demo seed data",
            "actorId": None,
            "actorRunId": None,
            "reviewCount": len(sample_reviews),
        },
        "branches": list(branches_by_id.values()),
        "reviews": sample_reviews,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Wrote demo dataset to {OUTPUT_PATH.relative_to(ROOT)}")


def review(
    branch_id: str,
    branch_name: str,
    review_id: str,
    reviewer_name: str,
    rating: int,
    published_at: str,
    comment: str,
    is_local_guide: bool = False,
    owner_response_text: str = "",
) -> dict:
    return {
        "id": review_id,
        "branchId": branch_id,
        "branchName": branch_name,
        "reviewerName": reviewer_name,
        "reviewerUrl": None,
        "reviewerReviewCount": 0,
        "isLocalGuide": is_local_guide,
        "rating": rating,
        "comment": comment,
        "commentTranslated": "",
        "publishedAt": published_at,
        "publishedLabel": "",
        "reviewUrl": None,
        "reviewSource": "Google",
        "ownerResponseText": owner_response_text,
        "ownerResponseDate": published_at if owner_response_text else None,
        "reviewImageUrls": [],
        "language": "en",
        "translatedLanguage": None,
        "scrapedAt": published_at,
        "placeId": None,
        "cid": None,
        "fid": None,
        "placeUrl": None,
        "title": None,
    }


if __name__ == "__main__":
    main()
