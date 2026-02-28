"""OAuth authentication manager for Microsoft 365."""

from datetime import datetime, timedelta, timezone
from typing import Any

import msal

from config.logging_config import logger

from .token_store import TokenStore

# Microsoft Graph scopes
BASE_SCOPES = [
    "User.Read",
    "Files.ReadWrite",
    "Tasks.ReadWrite",
    "offline_access",
]

SHAREPOINT_SCOPES = [
    "Sites.ReadWrite.All",
]

TEAMS_SCOPES = [
    "ChannelMessage.Read.All",
]


class OAuthManager:
    """Manages OAuth flow for Microsoft 365 multi-tenant authentication."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_store: TokenStore,
        authority: str = "https://login.microsoftonline.com/common",
    ):
        """Initialize OAuth manager.

        Args:
            client_id: Azure AD application client ID
            client_secret: Azure AD application client secret
            redirect_uri: OAuth redirect URI
            token_store: Token storage instance
            authority: Azure AD authority URL
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_store = token_store
        self.authority = authority

        # Initialize MSAL client
        self._msal_app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=authority,
        )

    def get_authorization_url(
        self,
        scopes: list[str] | None = None,
        state: str | None = None,
    ) -> str:
        """Generate OAuth authorization URL.

        Args:
            scopes: Requested scopes (defaults to BASE_SCOPES + SHAREPOINT_SCOPES)
            state: Optional state parameter for CSRF protection

        Returns:
            Authorization URL for redirect
        """
        if scopes is None:
            scopes = BASE_SCOPES + SHAREPOINT_SCOPES

        auth_url = self._msal_app.get_authorization_request_url(
            scopes=scopes,
            state=state,
            redirect_uri=self.redirect_uri,
        )

        return auth_url

    async def handle_callback(
        self,
        code: str,
        tenant_name: str,
        role: str = "guest",
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Handle OAuth callback and exchange code for tokens.

        Args:
            code: Authorization code from callback
            tenant_name: Friendly name for the tenant
            role: User role in tenant (owner/guest)
            scopes: Requested scopes

        Returns:
            Token response dict

        Raises:
            Exception if token exchange fails
        """
        if scopes is None:
            scopes = BASE_SCOPES + SHAREPOINT_SCOPES

        result = self._msal_app.acquire_token_by_authorization_code(
            code=code,
            scopes=scopes,
            redirect_uri=self.redirect_uri,
        )

        if "error" in result:
            error = result.get("error_description", result.get("error", "Unknown"))
            logger.error(f"Token exchange failed: {error}")
            raise Exception(f"OAuth error: {error}")

        # Extract tenant ID from token
        id_token_claims = result.get("id_token_claims", {})
        tenant_id = id_token_claims.get("tid", "unknown")

        # Calculate expiration
        expires_in = result.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Store tokens
        self.token_store.store_tokens(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            access_token=result["access_token"],
            refresh_token=result.get("refresh_token", ""),
            expires_at=expires_at,
            scopes=scopes,
            role=role,
        )

        logger.info(f"Successfully authenticated tenant {tenant_name} ({tenant_id})")

        return {
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
            "expires_at": expires_at.isoformat(),
            "scopes": scopes,
        }

    async def refresh_token(self, tenant_id: str) -> bool:
        """Refresh access token for a tenant.

        Args:
            tenant_id: Azure AD tenant ID

        Returns:
            True if refresh successful
        """
        tokens = self.token_store.get_tokens(tenant_id)
        if not tokens:
            logger.error(f"No tokens found for tenant {tenant_id}")
            return False

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            logger.error(f"No refresh token for tenant {tenant_id}")
            return False

        try:
            result = self._msal_app.acquire_token_by_refresh_token(
                refresh_token=refresh_token,
                scopes=tokens.get("scopes", BASE_SCOPES),
            )

            if "error" in result:
                error = result.get("error_description", result.get("error"))
                logger.error(f"Token refresh failed for {tenant_id}: {error}")
                self.token_store.mark_failure(tenant_id)
                return False

            # Calculate new expiration
            expires_in = result.get("expires_in", 3600)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            # Update stored tokens
            self.token_store.store_tokens(
                tenant_id=tenant_id,
                tenant_name=tokens["tenant_name"],
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token", refresh_token),
                expires_at=expires_at,
                scopes=tokens.get("scopes", []),
                role=tokens.get("role", "guest"),
            )

            logger.debug(f"Refreshed token for tenant {tenant_id}")
            return True

        except Exception as e:
            logger.error(f"Token refresh exception for {tenant_id}: {e}")
            self.token_store.mark_failure(tenant_id)
            return False

    async def get_valid_token(self, tenant_id: str) -> str | None:
        """Get a valid access token, refreshing if necessary.

        Args:
            tenant_id: Azure AD tenant ID

        Returns:
            Valid access token or None
        """
        tokens = self.token_store.get_tokens(tenant_id)
        if not tokens:
            return None

        # Check if token is expired or about to expire
        if self.token_store.is_token_expired(tenant_id):
            if not await self.refresh_token(tenant_id):
                return None
            tokens = self.token_store.get_tokens(tenant_id)

        return tokens.get("access_token") if tokens else None

    async def revoke_tenant(self, tenant_id: str) -> None:
        """Revoke and delete tokens for a tenant.

        Args:
            tenant_id: Azure AD tenant ID
        """
        # Microsoft doesn't have a revocation endpoint, just delete locally
        self.token_store.delete_tenant(tenant_id)
        logger.info(f"Revoked tokens for tenant {tenant_id}")
