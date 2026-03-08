"""
YouTube OAuth 2.0 authentication.

First run: opens browser for consent and saves token to credentials/token.pickle.
Subsequent runs: loads and auto-refreshes the cached token.

Setup:
  1. Go to https://console.cloud.google.com/
  2. Create a project → Enable "YouTube Data API v3"
  3. Create OAuth 2.0 credentials (Desktop app)
  4. Download as credentials/client_secrets.json
"""

import os
import pickle
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

_BASE = Path(__file__).parent.parent
_TOKEN_PATH = _BASE / "credentials" / "token.pickle"
_SECRETS_PATH = _BASE / "credentials" / "client_secrets.json"


def _run_manual_flow(flow: InstalledAppFlow) -> Credentials:
    """
    Manual OAuth flow: print URL → user authorizes → paste the redirect URL back.

    Works even when localhost redirect fails (ERR_CONNECTION_REFUSED) because
    the auth code is embedded in the URL query string.
    """
    import urllib.parse

    flow.redirect_uri = "http://localhost:8080/"
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    print("\n" + "=" * 70)
    print("YouTube OAuth Authorization Required")
    print("=" * 70)
    print("\n1. Open this URL in your browser:\n")
    print(f"   {auth_url}\n")
    print("2. Authorize the app.")
    print("3. You will be redirected to localhost (it may show an error page).")
    print("4. Copy the FULL URL from the browser address bar and paste it below.\n")

    redirected_url = input("Paste the full redirect URL here: ").strip()

    # Extract the 'code' query parameter from the redirect URL
    parsed = urllib.parse.urlparse(redirected_url)
    params = urllib.parse.parse_qs(parsed.query)
    if "code" not in params:
        raise ValueError(
            "No 'code' found in the URL. Make sure you copied the full URL."
        )
    code = params["code"][0]

    flow.fetch_token(code=code)
    return flow.credentials


def get_youtube_client():
    """
    Return an authenticated YouTube API client.

    Raises FileNotFoundError if client_secrets.json is missing.
    """
    if not _SECRETS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {_SECRETS_PATH}\n"
            "Download OAuth 2.0 credentials from Google Cloud Console "
            "(APIs & Services → Credentials → Create → Desktop app) "
            "and save as credentials/client_secrets.json"
        )

    creds: Credentials | None = None

    if _TOKEN_PATH.exists():
        with open(_TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(_SECRETS_PATH), SCOPES)
            creds = _run_manual_flow(flow)

        _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)
