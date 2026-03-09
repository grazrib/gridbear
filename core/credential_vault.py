"""Credential Vault — secure credential storage for agent form-filling.

Credentials are encrypted via the existing SecretsManager (AES-256-GCM).
Each service entry is stored as ``vault:{service_id}`` in secrets.db.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)

_SERVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_VAULT_PREFIX = "vault:"  # global (unused, kept for reference)


def _user_prefix(user_id: str) -> str:
    """Return the secrets key prefix for a user's vault entries."""
    return f"vault:{user_id}:"


def resolve_user_id(raw_id: str) -> str:
    """Resolve any user identifier to the username used for vault keys.

    Tries in order:
    1. Direct match on User.username
    2. Match on platform_username in UserPlatform → User.username
    3. Fallback: return raw_id stripped of @ and lowered
    """
    raw_id = raw_id.strip().lstrip("@").lower()

    try:
        from core.models.user import User

        # 1. Direct match on username
        if User.exists_sync(username=raw_id):
            return raw_id
    except Exception:
        pass

    # 2. Match on platform username
    try:
        from core.config_models import UserPlatform
        from core.models.user import User

        rows = UserPlatform.search_sync([("platform_username", "=", raw_id)])
        if rows:
            user = User.get_sync(id=rows[0]["user_id"])
            if user:
                return user["username"]
    except Exception:
        pass

    return raw_id


_MASK = "********"


def validate_service_id(service_id: str) -> bool:
    """Return *True* if *service_id* matches ``^[a-z0-9][a-z0-9_-]{0,62}$``."""
    return bool(_SERVICE_ID_RE.match(service_id))


# --- dataclasses -----------------------------------------------------------


@dataclass
class VaultCredential:
    key: str
    value: str
    secret: bool = True


@dataclass
class VaultEntry:
    service_id: str
    name: str
    url: str = ""
    notes: str = ""
    credentials: list[VaultCredential] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Full dict including secret values (for storage)."""
        return {
            "name": self.name,
            "url": self.url,
            "notes": self.notes,
            "credentials": [asdict(c) for c in self.credentials],
        }

    def to_safe_dict(self) -> dict:
        """Dict for the agent — secret values are masked."""
        creds = []
        for c in self.credentials:
            creds.append(
                {
                    "key": c.key,
                    "value": _MASK if c.secret else c.value,
                    "secret": c.secret,
                }
            )
        return {
            "service_id": self.service_id,
            "name": self.name,
            "url": self.url,
            "notes": self.notes,
            "credentials": creds,
        }

    @classmethod
    def from_stored(cls, service_id: str, data: dict) -> VaultEntry:
        """Construct from the JSON stored in secrets.db."""
        creds = [
            VaultCredential(
                key=c["key"],
                value=c["value"],
                secret=c.get("secret", True),
            )
            for c in data.get("credentials", [])
        ]
        return cls(
            service_id=service_id,
            name=data.get("name", service_id),
            url=data.get("url", ""),
            notes=data.get("notes", ""),
            credentials=creds,
        )


# --- CRUD helpers -----------------------------------------------------------


def _secrets():
    """Lazily import the global SecretsManager singleton."""
    from ui.secrets_manager import secrets_manager

    return secrets_manager


def list_services(user_id: str) -> list[dict]:
    """Return a list of safe dicts (no secret values) for a user's vault entries."""
    sm = _secrets()
    prefix = _user_prefix(user_id)
    entries = []
    for item in sm.list_keys():
        key_name: str = item["key_name"]
        if not key_name.startswith(prefix):
            continue
        service_id = key_name[len(prefix) :]
        raw = sm.get_plain(key_name, fallback_env=False)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            entry = VaultEntry.from_stored(service_id, data)
            entries.append(entry.to_safe_dict())
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Vault: corrupt entry %s: %s", key_name, exc)
    return entries


def get_service(user_id: str, service_id: str) -> VaultEntry | None:
    """Return the full VaultEntry (with real values) or *None*."""
    sm = _secrets()
    raw = sm.get_plain(f"{_user_prefix(user_id)}{service_id}", fallback_env=False)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return VaultEntry.from_stored(service_id, data)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Vault: corrupt entry %s: %s", service_id, exc)
        return None


def save_service(user_id: str, entry: VaultEntry) -> None:
    """Save (create or update) a vault entry for a user."""
    if not validate_service_id(entry.service_id):
        raise ValueError(f"Invalid service_id: {entry.service_id!r}")
    sm = _secrets()
    sm.set(
        f"{_user_prefix(user_id)}{entry.service_id}",
        json.dumps(entry.to_dict()),
        description=f"Vault ({user_id}): {entry.name}",
    )
    logger.info("Vault: saved service %s for user %s", entry.service_id, user_id)


def delete_service(user_id: str, service_id: str) -> bool:
    """Delete a vault entry. Returns *True* if it existed."""
    sm = _secrets()
    deleted = sm.delete(f"{_user_prefix(user_id)}{service_id}")
    if deleted:
        logger.info("Vault: deleted service %s for user %s", service_id, user_id)
    return deleted
