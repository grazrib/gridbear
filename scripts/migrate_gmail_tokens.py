#!/usr/bin/env python3
"""Migrate Gmail OAuth tokens from files to encrypted secrets.db.

Run this script once to migrate existing tokens:
    python scripts/migrate_gmail_tokens.py

After migration, you can delete the old credential directories.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ui.secrets_manager import secrets_manager


def migrate_tokens():
    """Migrate Gmail tokens from file system to secrets.db."""
    credentials_dir = Path(__file__).parent.parent / "credentials"

    if not credentials_dir.exists():
        print("No credentials directory found. Nothing to migrate.")
        return

    migrated = 0
    skipped = 0
    errors = 0

    # Find all email directories (those with token.json)
    for item in credentials_dir.iterdir():
        if not item.is_dir():
            continue

        # Skip non-email directories
        if "@" not in item.name:
            continue

        email = item.name
        token_path = item / "token.json"
        creds_path = item / "credentials.json"

        if not token_path.exists():
            print(f"  Skip {email}: no token.json")
            skipped += 1
            continue

        # Check if already migrated
        secret_key = f"gmail_token_{email}"
        if secrets_manager.exists(secret_key):
            print(f"  Skip {email}: already in secrets.db")
            skipped += 1
            continue

        try:
            # Read token file
            with open(token_path) as f:
                token_data = json.load(f)

            # Read credentials file if exists (for client_id/secret)
            if creds_path.exists():
                with open(creds_path) as f:
                    creds_data = json.load(f)
                    cred_config = creds_data.get("web") or creds_data.get(
                        "installed", {}
                    )
                    # Add client credentials if not in token
                    if "client_id" not in token_data:
                        token_data["client_id"] = cred_config.get("client_id")
                    if "client_secret" not in token_data:
                        token_data["client_secret"] = cred_config.get("client_secret")

            # Store encrypted
            secrets_manager.set(
                secret_key,
                json.dumps(token_data),
                description=f"Gmail OAuth token for {email}",
            )
            print(f"  Migrated {email}")
            migrated += 1

        except Exception as e:
            print(f"  Error migrating {email}: {e}")
            errors += 1

    print("\nMigration complete:")
    print(f"  Migrated: {migrated}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {errors}")

    if migrated > 0:
        print("\nYou can now delete the old credential directories:")
        for item in credentials_dir.iterdir():
            if item.is_dir() and "@" in item.name:
                print(f"  rm -rf {item}")


if __name__ == "__main__":
    print("Migrating Gmail tokens from files to encrypted secrets.db...\n")
    migrate_tokens()
