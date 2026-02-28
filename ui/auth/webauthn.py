"""WebAuthn/Passkeys management.

Provides FIDO2/WebAuthn-based 2FA with:
- Passkey registration (fingerprint, Face ID, security keys)
- Passkey authentication as alternative to TOTP
- Multiple credentials per user
"""

import os

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

RP_ID = os.getenv("WEBAUTHN_RP_ID", "localhost")
RP_NAME = os.getenv("WEBAUTHN_RP_NAME", "GridBear")
ORIGIN = os.getenv("WEBAUTHN_ORIGIN", "http://localhost:8088")


class WebAuthnManager:
    """Manages WebAuthn/passkey-based two-factor authentication."""

    def __init__(
        self,
        rp_id: str = RP_ID,
        rp_name: str = RP_NAME,
        origin: str = ORIGIN,
    ):
        self.rp_id = rp_id
        self.rp_name = rp_name
        self.origin = origin

    def get_registration_options(
        self,
        user_id: int,
        username: str,
        existing_credentials: list[dict] | None = None,
    ) -> tuple[str, bytes]:
        """Generate registration options for a new passkey.

        Returns:
            Tuple of (options_json, challenge_bytes)
        """
        exclude = []
        if existing_credentials:
            for cred in existing_credentials:
                exclude.append(PublicKeyCredentialDescriptor(id=cred["credential_id"]))

        options = generate_registration_options(
            rp_id=self.rp_id,
            rp_name=self.rp_name,
            user_id=str(user_id).encode(),
            user_name=username,
            user_display_name=username,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
            exclude_credentials=exclude,
        )

        return options_to_json(options), options.challenge

    def verify_registration(
        self,
        response_json: str,
        expected_challenge: bytes,
    ) -> dict:
        """Verify a registration response from the browser.

        Returns:
            Dict with credential_id, public_key, sign_count
        Raises:
            Exception on verification failure
        """
        verification = verify_registration_response(
            credential=response_json,
            expected_challenge=expected_challenge,
            expected_origin=self.origin,
            expected_rp_id=self.rp_id,
        )

        return {
            "credential_id": verification.credential_id,
            "public_key": verification.credential_public_key,
            "sign_count": verification.sign_count,
        }

    def get_authentication_options(
        self,
        credentials: list[dict],
    ) -> tuple[str, bytes]:
        """Generate authentication options for existing passkeys.

        Args:
            credentials: List of stored credential dicts with credential_id

        Returns:
            Tuple of (options_json, challenge_bytes)
        """
        allow = [
            PublicKeyCredentialDescriptor(id=cred["credential_id"])
            for cred in credentials
        ]

        options = generate_authentication_options(
            rp_id=self.rp_id,
            allow_credentials=allow,
            user_verification=UserVerificationRequirement.PREFERRED,
        )

        return options_to_json(options), options.challenge

    def verify_authentication(
        self,
        response_json: str,
        expected_challenge: bytes,
        credential_public_key: bytes,
        credential_current_sign_count: int,
    ) -> int:
        """Verify an authentication response from the browser.

        Returns:
            The new sign count
        Raises:
            Exception on verification failure
        """
        verification = verify_authentication_response(
            credential=response_json,
            expected_challenge=expected_challenge,
            expected_origin=self.origin,
            expected_rp_id=self.rp_id,
            credential_public_key=credential_public_key,
            credential_current_sign_count=credential_current_sign_count,
        )

        return verification.new_sign_count

    @staticmethod
    def challenge_to_session(challenge: bytes) -> str:
        """Encode challenge bytes for session storage."""
        return bytes_to_base64url(challenge)

    @staticmethod
    def challenge_from_session(challenge_b64: str) -> bytes:
        """Decode challenge bytes from session storage."""
        return base64url_to_bytes(challenge_b64)


webauthn_manager = WebAuthnManager()
