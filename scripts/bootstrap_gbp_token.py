#!/usr/bin/env python3
"""Run a one-time OAuth flow and print a Google Business Profile refresh token."""

from __future__ import annotations

import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Optional
from urllib import parse

from gbp_common import (
    BUSINESS_MANAGE_SCOPE,
    OAUTH_AUTH_URL,
    exchange_authorization_code,
    first_env,
    require_env,
)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Capture the OAuth callback code from Google's redirect."""

    server_version = "MayfairOAuth/1.0"
    callback_data: Dict[str, str] = {}
    callback_event = threading.Event()

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = parse.urlparse(self.path)
        query = parse.parse_qs(parsed.query)
        OAuthCallbackHandler.callback_data = {key: values[0] for key, values in query.items() if values}

        if query.get("code"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authentication complete</h1>"
                b"<p>You can return to the terminal.</p></body></html>"
            )
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authentication failed</h1>"
                b"<p>No authorization code was received.</p></body></html>"
            )

        OAuthCallbackHandler.callback_event.set()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003 - stdlib naming
        return


def main() -> int:
    client_id = require_env("GBP_CLIENT_ID")
    client_secret = require_env("GBP_CLIENT_SECRET")
    port = int(first_env("GBP_OAUTH_REDIRECT_PORT") or "8765")
    redirect_uri = first_env("GBP_REDIRECT_URI") or f"http://127.0.0.1:{port}/oauth2callback"
    timeout_seconds = int(first_env("GBP_OAUTH_TIMEOUT_SECONDS") or "300")
    state = secrets.token_urlsafe(24)
    reset_callback_state()

    auth_url = build_authorization_url(client_id=client_id, redirect_uri=redirect_uri, state=state)
    server = HTTPServer(("127.0.0.1", port), OAuthCallbackHandler)
    server.timeout = 1
    worker = threading.Thread(target=serve_until_callback, args=(server,), daemon=True)
    worker.start()

    print("Open this URL in the Google account that manages the Mayfair Gearbox profile:")
    print(auth_url)
    print("")
    print("Waiting for the OAuth callback on", redirect_uri)
    print("If the browser says Authentication complete but the terminal does not move,")
    print("wait about 5-10 seconds, then press Ctrl+C once and paste the full browser URL.")
    webbrowser.open(auth_url)

    try:
        if not OAuthCallbackHandler.callback_event.wait(timeout=timeout_seconds):
            callback_data = prompt_for_callback_url()
        else:
            callback_data = OAuthCallbackHandler.callback_data
    except KeyboardInterrupt:
        print("")
        callback_data = prompt_for_callback_url()
    finally:
        OAuthCallbackHandler.callback_event.set()
        worker.join(timeout=2)
        server.server_close()

    if not callback_data:
        print("No callback data was received.")
        return 1

    if callback_data.get("state") != state:
        print("OAuth state mismatch. Aborting.")
        return 1

    if "error" in callback_data:
        print(f"Google returned an OAuth error: {callback_data['error']}")
        return 1

    code = callback_data.get("code")
    if not code:
        print("No authorization code was returned by Google.")
        return 1

    token_data = exchange_authorization_code(
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=redirect_uri,
    )

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        print(
            "Google did not return a refresh token. Re-run this script with a new OAuth consent "
            "grant and make sure prompt=consent is allowed."
        )
        return 1

    print("")
    print("Google Business Profile OAuth setup completed.")
    print("Add these GitHub repository secrets next:")
    print(f"- GBP_CLIENT_ID = {client_id}")
    print("- GBP_CLIENT_SECRET = <the client secret you already used>")
    print(f"- GBP_REFRESH_TOKEN = {refresh_token}")
    print("")
    print("Then run:")
    print("python3 scripts/list_gbp_locations.py")
    return 0


def build_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": BUSINESS_MANAGE_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return f"{OAUTH_AUTH_URL}?{query}"


def prompt_for_callback_url() -> Dict[str, str]:
    print("Paste the full browser URL from the authentication-complete page here:")
    pasted = input("> ").strip()
    if not pasted:
        return {}
    return parse_callback_input(pasted)


def parse_callback_input(value: str) -> Dict[str, str]:
    value = value.strip()
    if not value:
        return {}

    if value.startswith("http://") or value.startswith("https://"):
        parsed = parse.urlparse(value)
        query = parse.parse_qs(parsed.query)
        return {key: values[0] for key, values in query.items() if values}

    if "code=" in value and "state=" in value:
        query = parse.parse_qs(value)
        return {key: values[0] for key, values in query.items() if values}

    return {"code": value}


def reset_callback_state() -> None:
    OAuthCallbackHandler.callback_data = {}
    OAuthCallbackHandler.callback_event.clear()


def serve_until_callback(server: HTTPServer) -> None:
    while not OAuthCallbackHandler.callback_event.is_set():
        server.handle_request()
        time.sleep(0.05)


if __name__ == "__main__":
    raise SystemExit(main())
