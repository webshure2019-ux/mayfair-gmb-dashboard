#!/usr/bin/env python3
"""Shared Google Business Profile API helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib import error, parse, request


BUSINESS_MANAGE_SCOPE = "https://www.googleapis.com/auth/business.manage"
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
ACCOUNTS_API_BASE = "https://mybusinessaccountmanagement.googleapis.com/v1"
BUSINESS_INFO_API_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"
REVIEWS_API_BASE = "https://mybusiness.googleapis.com/v4"


class GoogleApiError(RuntimeError):
    """Raised when a Google API call returns a non-success response."""


def env_flag(name: str, *legacy_names: str) -> bool:
    return first_env(name, *legacy_names).strip().lower() in {"1", "true", "yes", "on"}


def first_env(name: str, *legacy_names: str) -> str:
    for env_name in (name, *legacy_names):
        value = os.getenv(env_name)
        if value is not None:
            return value
    return ""


def require_env(name: str, *legacy_names: str) -> str:
    value = first_env(name, *legacy_names).strip()
    if not value:
        aliases = ", ".join([name, *legacy_names])
        raise KeyError(f"Missing required environment variable. Expected one of: {aliases}")
    return value


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def normalize_text(value: Optional[str]) -> str:
    return " ".join(str(value or "").lower().replace("&", "and").replace("-", " ").split())


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
    blocked_titles = [
        normalize_text(value)
        for value in (branch.get("blockedTitles") or [])
        if value
    ]
    return bool(normalized_title and normalized_title in blocked_titles)


def compose_google_location_name(account_name: str, location_name: str) -> str:
    account_name = str(account_name or "").strip()
    location_name = str(location_name or "").strip()

    if location_name.startswith("accounts/"):
        return location_name

    if account_name.startswith("accounts/") and location_name.startswith("locations/"):
        return f"{account_name}/{location_name}"

    raise ValueError(
        f"Could not compose a Google location name from account={account_name!r} "
        f"and location={location_name!r}."
    )


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> Dict[str, Any]:
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    token_data = google_api_request("POST", OAUTH_TOKEN_URL, payload=payload, form_encoded=True)

    if not token_data.get("access_token"):
        raise GoogleApiError("Google OAuth token refresh did not return an access_token.")

    return token_data


def exchange_authorization_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    token_data = google_api_request("POST", OAUTH_TOKEN_URL, payload=payload, form_encoded=True)

    if not token_data.get("access_token"):
        raise GoogleApiError("Google OAuth authorization code exchange did not return an access_token.")

    return token_data


def google_api_request(
    method: str,
    url: str,
    access_token: Optional[str] = None,
    params: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    form_encoded: bool = False,
    timeout: int = 120,
) -> Any:
    query = parse.urlencode(params or {})
    request_url = f"{url}?{query}" if query else url

    data = None
    headers = {
        "Accept": "application/json",
    }

    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    if payload is not None:
        if form_encoded:
            data = parse.urlencode(payload).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

    http_request = request.Request(request_url, method=method, data=data, headers=headers)

    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        message = extract_google_error_message(detail)
        raise GoogleApiError(f"Google API request failed: {exc.code} {message}") from exc
    except error.URLError as exc:
        raise GoogleApiError(f"Google API request failed: {exc.reason}") from exc

    if not raw_body:
        return {}

    return json.loads(raw_body)


def fetch_paginated_collection(
    url: str,
    access_token: str,
    items_key: str,
    params: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    page_token = ""
    base_params = dict(params or {})

    while True:
        request_params = dict(base_params)
        if page_token:
            request_params["pageToken"] = page_token

        response = google_api_request("GET", url, access_token=access_token, params=request_params)
        collected.extend(response.get(items_key) or [])
        page_token = str(response.get("nextPageToken") or "").strip()

        if not page_token:
            return collected


def fetch_accessible_accounts(access_token: str) -> List[Dict[str, Any]]:
    return fetch_paginated_collection(
        f"{ACCOUNTS_API_BASE}/accounts",
        access_token=access_token,
        items_key="accounts",
        params={"pageSize": "20"},
    )


def fetch_locations_for_account(access_token: str, account_name: str) -> List[Dict[str, Any]]:
    return fetch_paginated_collection(
        f"{BUSINESS_INFO_API_BASE}/{quote_resource_name(account_name)}/locations",
        access_token=access_token,
        items_key="locations",
        params={
            "pageSize": "100",
            "orderBy": "title",
            "readMask": "name,title,storeCode,websiteUri,metadata.placeId,metadata.mapsUri,metadata.newReviewUri",
        },
    )


def simplify_location(account_name: str, location: Dict[str, Any]) -> Dict[str, Any]:
    location_name = str(location.get("name") or "").strip()
    metadata = location.get("metadata") or {}
    return {
        "accountName": account_name,
        "locationName": location_name,
        "googleLocationName": compose_google_location_name(account_name, location_name),
        "title": location.get("title") or "",
        "storeCode": location.get("storeCode") or "",
        "websiteUri": location.get("websiteUri") or "",
        "placeId": metadata.get("placeId") or "",
        "mapsUri": metadata.get("mapsUri") or "",
        "newReviewUri": metadata.get("newReviewUri") or "",
    }


def extract_google_error_message(detail: str) -> str:
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return detail.strip() or "Unknown Google API error."

    error_payload = payload.get("error") or {}
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        status = error_payload.get("status")
        if message and status:
            return f"{status}: {message}"
        if message:
            return str(message)

    return detail.strip() or "Unknown Google API error."


def parse_optional_int(value: str, field_name: str) -> Optional[int]:
    value = str(value or "").strip()
    if not value:
        return None

    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer if provided.") from exc

    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero if provided.")

    return parsed


def quote_resource_name(resource_name: str) -> str:
    return parse.quote(resource_name, safe="/")


def find_best_location_match(
    branch: Dict[str, Any],
    locations: Iterable[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    candidates = branch_candidates(branch)
    exact_matches: List[Dict[str, Any]] = []
    fuzzy_matches: List[Dict[str, Any]] = []

    for location in locations:
        title = normalize_text(location.get("title"))
        if not title:
            continue
        if blocked_title(title, branch):
            continue

        if any(candidate and candidate == title for candidate in candidates):
            exact_matches.append(location)
            continue

        if any(candidate and (title.startswith(candidate) or candidate.startswith(title)) for candidate in candidates):
            fuzzy_matches.append(location)

    if len(exact_matches) == 1:
        return exact_matches[0]

    if len(exact_matches) > 1:
        return None

    if len(fuzzy_matches) == 1:
        return fuzzy_matches[0]

    return None
