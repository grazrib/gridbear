"""Application-layer encryption for user data at rest.

Uses AES-256-GCM with the same master key as SecretsManager (config/secrets.key).
Storage format: base64(nonce_12bytes + ciphertext) as a single TEXT string.
"""

import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Key search paths — same as ui/secrets_manager.py (no import dependency on ui/)
_BASE_DIR = Path(__file__).resolve().parent.parent
KEY_PATHS = [
    _BASE_DIR / "config" / "secrets.key",
    Path.home() / ".ssh" / "id_ed25519",
    Path.home() / ".ssh" / "id_rsa",
    Path("/root/.ssh/id_ed25519"),
    Path("/root/.ssh/id_rsa"),
    Path("/app/config/secrets.key"),
]
MASTER_KEY_ENV = "GRIDBEAR_MASTER_KEY"

_cached_key: bytes | None = None


def _find_key_file() -> Path | None:
    for p in KEY_PATHS:
        if p.exists():
            return p
    return None


def _get_key() -> bytes:
    """Derive a 32-byte AES key from the master key source."""
    global _cached_key
    if _cached_key is not None:
        return _cached_key

    key_file = _find_key_file()
    if key_file:
        raw = key_file.read_bytes()
        _cached_key = hashlib.sha256(raw).digest()
        return _cached_key

    env_val = os.environ.get(MASTER_KEY_ENV)
    if env_val:
        _cached_key = hashlib.sha256(env_val.encode()).digest()
        return _cached_key

    raise RuntimeError(
        "No encryption key found. Create config/secrets.key or set GRIDBEAR_MASTER_KEY."
    )


def encrypt(plaintext: str) -> str:
    """Encrypt a string using AES-256-GCM.

    Returns base64(nonce_12bytes + ciphertext).
    """
    key = _get_key()
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(encrypted: str) -> str:
    """Decrypt a base64(nonce + ciphertext) string."""
    key = _get_key()
    raw = base64.b64decode(encrypted)
    nonce = raw[:12]
    ct = raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")


def is_encrypted(value: str) -> bool:
    """Heuristic check: is the value an encrypted blob?

    Tries base64-decode and checks that the decoded length is > 28 bytes
    (12 nonce + 16 GCM tag minimum). Used by migration scripts and the
    Encrypted field to avoid double-encrypting or decrypting plaintext.
    """
    if not value or len(value) < 40:
        return False
    try:
        raw = base64.b64decode(value, validate=True)
        # AES-GCM: 12 nonce + at least 16 tag + 1 byte ciphertext = 29 min
        return len(raw) >= 29
    except Exception:
        return False
