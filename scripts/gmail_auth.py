#!/usr/bin/env python3
"""
Gmail OAuth2 Authentication Script

Generates a token.json with read and send permissions for Gmail.

Usage:
    # Step 1: Get the authorization URL
    python scripts/gmail_auth.py

    # Step 2: Open URL in browser, authorize, copy the code

    # Step 3: Complete with the code
    python scripts/gmail_auth.py <CODE>

Requirements:
    pip install google-auth-oauthlib google-api-python-client
"""

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

CREDENTIALS_DIR = Path(__file__).parent.parent / "credentials"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
TOKEN_FILE = CREDENTIALS_DIR / "token.json"


def main():
    if not CREDENTIALS_FILE.exists():
        print(f"Error: {CREDENTIALS_FILE} not found")
        print("Download OAuth credentials from Google Cloud Console")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"

    # If code provided as argument, complete the flow
    if len(sys.argv) > 1:
        code = sys.argv[1]
        print("Completing OAuth flow with code...")
        flow.fetch_token(code=code)
        creds = flow.credentials

        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes),
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        }

        TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
        print(f"Token saved to: {TOKEN_FILE}")
        print("Restart Docker container: docker compose restart")
    else:
        # Show authorization URL
        auth_url, _ = flow.authorization_url(prompt="consent")
        print("=" * 60)
        print("Step 1: Open this URL in browser:")
        print("=" * 60)
        print(auth_url)
        print("=" * 60)
        print("\nStep 2: Authorize and copy the code")
        print("\nStep 3: Run again with the code:")
        print(f"  python {sys.argv[0]} <CODE>")


if __name__ == "__main__":
    main()
