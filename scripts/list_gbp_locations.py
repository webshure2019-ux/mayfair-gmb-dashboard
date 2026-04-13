#!/usr/bin/env python3
"""List accessible Google Business Profile locations and suggest Mayfair branch matches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from gbp_common import (
    blocked_title,
    fetch_accessible_accounts,
    fetch_locations_for_account,
    find_best_location_match,
    read_json,
    refresh_access_token,
    require_env,
    simplify_location,
)


ROOT = Path(__file__).resolve().parents[1]
BRANCHES_PATH = ROOT / "config" / "branches.json"


def main() -> int:
    client_id = require_env("GBP_CLIENT_ID")
    client_secret = require_env("GBP_CLIENT_SECRET")
    refresh_token = require_env("GBP_REFRESH_TOKEN")

    token_data = refresh_access_token(client_id, client_secret, refresh_token)
    access_token = token_data["access_token"]

    accounts = fetch_accessible_accounts(access_token)
    if not accounts:
        print("No accessible Google Business Profile accounts were returned for this OAuth user.")
        return 1

    simplified_accounts: List[Dict[str, Any]] = []
    all_locations: List[Dict[str, Any]] = []

    for account in accounts:
        account_name = account.get("name") or ""
        account_display_name = account.get("accountName") or account_name
        locations = [
            simplify_location(account_name, location)
            for location in fetch_locations_for_account(access_token, account_name)
        ]
        simplified_accounts.append(
            {
                "name": account_name,
                "accountName": account_display_name,
                "type": account.get("type") or account.get("accountType") or "",
                "locationCount": len(locations),
            }
        )
        all_locations.extend(locations)

    branches = read_json(BRANCHES_PATH)
    suggestions = build_branch_suggestions(branches, all_locations)

    print(
        json.dumps(
            {
                "accounts": simplified_accounts,
                "branchSuggestions": suggestions,
                "locations": all_locations,
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


def build_branch_suggestions(
    branches: List[Dict[str, Any]],
    all_locations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    suggestions: List[Dict[str, Any]] = []

    for branch in branches:
        candidate_locations = [
            location
            for location in all_locations
            if not blocked_title(location.get("title"), branch)
        ]
        configured_location_name = str(branch.get("googleLocationName") or "").strip()
        configured_match = next(
            (
                location
                for location in candidate_locations
                if location["googleLocationName"] == configured_location_name
            ),
            None,
        )
        suggested_match = configured_match or find_best_location_match(branch, candidate_locations)
        suggestions.append(
            {
                "branchId": branch["id"],
                "branchName": branch["name"],
                "configuredGoogleLocationName": configured_location_name or None,
                "suggestedTitle": (suggested_match or {}).get("title"),
                "suggestedGoogleLocationName": (suggested_match or {}).get("googleLocationName"),
                "suggestedPlaceId": (suggested_match or {}).get("placeId"),
                "suggestedMapsUri": (suggested_match or {}).get("mapsUri"),
            }
        )

    return suggestions


if __name__ == "__main__":
    raise SystemExit(main())
