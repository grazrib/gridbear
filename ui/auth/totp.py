"""TOTP (Time-based One-Time Password) management.

Provides Google Authenticator compatible 2FA with:
- TOTP secret generation and verification
- QR code generation for easy setup
- Encrypted secret storage via secrets_manager
"""

import base64
from io import BytesIO
from typing import Optional

import pyotp
import qrcode

from ui.secrets_manager import secrets_manager

ISSUER_NAME = "GridBear Admin"
TOTP_WINDOW = 1


class TOTPManager:
    """Manages TOTP-based two-factor authentication."""

    def __init__(self, issuer: str = ISSUER_NAME):
        self.issuer = issuer
        self.window = TOTP_WINDOW

    def generate_secret(self) -> str:
        """Generate a new random TOTP secret."""
        return pyotp.random_base32()

    def encrypt_secret(self, secret: str, user_id: int) -> str:
        """Encrypt TOTP secret for database storage.

        Uses the secrets_manager for AES-256-GCM encryption.
        """
        key_name = f"_totp_secret_{user_id}"
        secrets_manager.set(key_name, secret)
        return f"encrypted:{key_name}"

    def decrypt_secret(self, encrypted: str, user_id: int) -> Optional[str]:
        """Decrypt TOTP secret from database.

        Returns the plaintext secret or None if decryption fails.
        """
        if encrypted.startswith("encrypted:"):
            key_name = encrypted[10:]
            return secrets_manager.get_plain(key_name, fallback_env=False) or None
        return encrypted

    def get_provisioning_uri(self, secret: str, username: str) -> str:
        """Get the otpauth:// URI for authenticator apps."""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=username, issuer_name=self.issuer)

    def generate_qr_code(self, secret: str, username: str) -> str:
        """Generate a QR code image as base64 data URI.

        Returns a data URI that can be used directly in an <img> src.
        """
        uri = self.get_provisioning_uri(secret, username)

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(uri)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        b64_image = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{b64_image}"

    def verify_code(self, secret: str, code: str) -> bool:
        """Verify a TOTP code.

        Args:
            secret: The TOTP secret (plaintext)
            code: The 6-digit code to verify

        Returns:
            True if the code is valid (within window tolerance)
        """
        code = code.strip().replace(" ", "").replace("-", "")
        if not code.isdigit() or len(code) != 6:
            return False

        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=self.window)

    def get_current_code(self, secret: str) -> str:
        """Get the current TOTP code (for testing)."""
        totp = pyotp.TOTP(secret)
        return totp.now()


totp_manager = TOTPManager()
