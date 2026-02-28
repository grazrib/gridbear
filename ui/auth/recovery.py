"""Recovery code management for 2FA bypass.

Provides:
- Generation of one-time recovery codes
- Secure bcrypt hashing
- Verification with automatic invalidation
"""

import secrets
import string

import bcrypt

from ui.auth.database import auth_db

RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_LENGTH = 8
RECOVERY_CODE_ALPHABET = string.ascii_uppercase + string.digits


class RecoveryCodeManager:
    """Manages recovery codes for 2FA bypass."""

    def __init__(self):
        self.db = auth_db
        self.code_count = RECOVERY_CODE_COUNT
        self.code_length = RECOVERY_CODE_LENGTH

    def generate_codes(self, user_id: int) -> list[str]:
        """Generate new recovery codes for a user.

        Replaces any existing codes.
        Returns the plaintext codes (only shown once).
        """
        codes = []
        hashes = []

        for _ in range(self.code_count):
            code = self._generate_code()
            codes.append(code)
            hashes.append(self._hash_code(code))

        self.db.add_recovery_codes(user_id, hashes)

        return codes

    def verify_code(self, user_id: int, code: str) -> bool:
        """Verify a recovery code and mark it as used if valid.

        Args:
            user_id: The user ID
            code: The recovery code to verify

        Returns:
            True if the code was valid and has been consumed
        """
        code = self._normalize_code(code)

        unused_codes = self.db.get_unused_recovery_codes(user_id)

        for stored in unused_codes:
            if self._verify_hash(code, stored["code_hash"]):
                self.db.mark_recovery_code_used(stored["id"])
                return True

        return False

    def get_remaining_count(self, user_id: int) -> int:
        """Get the number of unused recovery codes for a user."""
        return len(self.db.get_unused_recovery_codes(user_id))

    def format_codes_for_display(self, codes: list[str]) -> list[str]:
        """Format codes with dashes for easier reading.

        Example: ABCD1234 -> ABCD-1234
        """
        formatted = []
        for code in codes:
            if len(code) == 8:
                formatted.append(f"{code[:4]}-{code[4:]}")
            else:
                formatted.append(code)
        return formatted

    def _generate_code(self) -> str:
        """Generate a single recovery code."""
        return "".join(
            secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(self.code_length)
        )

    def _normalize_code(self, code: str) -> str:
        """Normalize a code for verification."""
        return code.upper().replace("-", "").replace(" ", "").strip()

    def _hash_code(self, code: str) -> str:
        """Hash a recovery code with bcrypt."""
        return bcrypt.hashpw(code.encode(), bcrypt.gensalt(rounds=12)).decode()

    def _verify_hash(self, code: str, hashed: str) -> bool:
        """Verify a code against its hash."""
        try:
            return bcrypt.checkpw(code.encode(), hashed.encode())
        except Exception:
            return False


recovery_manager = RecoveryCodeManager()
