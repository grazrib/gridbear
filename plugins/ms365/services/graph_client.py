"""Microsoft Graph API client."""

from typing import Any

import httpx

from config.logging_config import logger

from ..utils.retry import RetryConfig, retry_with_backoff

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class GraphAPIError(Exception):
    """Exception for Graph API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GraphClient:
    """Async client for Microsoft Graph API."""

    def __init__(self, timeout: float = 30.0):
        """Initialize Graph client.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._retry_config = RetryConfig(
            max_retries=3,
            base_delay=1.0,
            max_delay=32.0,
            retryable_status_codes=(429, 500, 502, 503, 504),
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=GRAPH_API_BASE,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        token: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any] | bytes | None:
        """Make authenticated request to Graph API.

        Args:
            method: HTTP method
            endpoint: API endpoint (relative to base URL)
            token: Access token
            params: Query parameters
            json_data: JSON body data
            data: Raw body data
            content_type: Content type header

        Returns:
            Response data (dict for JSON, bytes for binary)

        Raises:
            GraphAPIError on failure
        """
        client = await self._get_client()

        headers = {
            "Authorization": f"Bearer {token}",
        }
        if content_type:
            headers["Content-Type"] = content_type

        async def _do_request():
            response = await client.request(
                method=method,
                url=endpoint,
                headers=headers,
                params=params,
                json=json_data,
                content=data,
            )

            if response.status_code == 204:
                return None

            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get(
                        "message", response.text
                    )
                except Exception:
                    error_msg = response.text

                raise GraphAPIError(
                    f"Graph API error: {error_msg}",
                    status_code=response.status_code,
                )

            # Return JSON or bytes based on content type
            content_type_header = response.headers.get("content-type", "")
            if "application/json" in content_type_header:
                return response.json()
            return response.content

        return await retry_with_backoff(_do_request, config=self._retry_config)

    async def get(
        self,
        endpoint: str,
        token: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | bytes | None:
        """GET request."""
        return await self._request("GET", endpoint, token, params=params)

    async def post(
        self,
        endpoint: str,
        token: str,
        json_data: dict[str, Any] | None = None,
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any] | None:
        """POST request."""
        return await self._request(
            "POST",
            endpoint,
            token,
            json_data=json_data,
            data=data,
            content_type=content_type,
        )

    async def put(
        self,
        endpoint: str,
        token: str,
        json_data: dict[str, Any] | None = None,
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any] | None:
        """PUT request."""
        return await self._request(
            "PUT",
            endpoint,
            token,
            json_data=json_data,
            data=data,
            content_type=content_type,
        )

    async def patch(
        self,
        endpoint: str,
        token: str,
        json_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """PATCH request."""
        return await self._request("PATCH", endpoint, token, json_data=json_data)

    async def delete(
        self,
        endpoint: str,
        token: str,
    ) -> None:
        """DELETE request."""
        await self._request("DELETE", endpoint, token)

    # ========== User Operations ==========

    async def get_me(self, token: str) -> dict[str, Any]:
        """Get current user profile.

        Args:
            token: Access token

        Returns:
            User profile dict
        """
        result = await self.get("/me", token)
        return result if isinstance(result, dict) else {}

    async def get_organization(self, token: str) -> dict[str, Any] | None:
        """Get organization info for current user.

        Args:
            token: Access token

        Returns:
            Organization info or None
        """
        try:
            result = await self.get("/organization", token)
            if isinstance(result, dict) and "value" in result:
                orgs = result["value"]
                return orgs[0] if orgs else None
        except GraphAPIError as e:
            if e.status_code == 403:
                # User may not have permission to view org
                return None
            raise
        return None

    # ========== Capability Discovery ==========

    async def discover_capabilities(self, token: str) -> dict[str, Any]:
        """Discover available capabilities for the token.

        Args:
            token: Access token

        Returns:
            Capabilities dict
        """
        capabilities = {
            "sharepoint": {"available": False, "sites": []},
            "planner": {"available": False, "plans": []},
            "onedrive": {"available": False},
            "teams": {"available": False},
        }

        # Test SharePoint access
        try:
            sites = await self.get("/sites?search=*", token, params={"$top": "5"})
            if isinstance(sites, dict) and "value" in sites:
                capabilities["sharepoint"]["available"] = True
                capabilities["sharepoint"]["sites"] = [
                    {"id": s["id"], "name": s.get("displayName", s.get("name", ""))}
                    for s in sites["value"]
                ]
        except GraphAPIError as e:
            logger.debug(f"SharePoint not available: {e}")

        # Test Planner access
        try:
            plans = await self.get("/me/planner/plans", token)
            if isinstance(plans, dict) and "value" in plans:
                capabilities["planner"]["available"] = True
                capabilities["planner"]["plans"] = [
                    {"id": p["id"], "title": p.get("title", "")}
                    for p in plans["value"][:10]
                ]
        except GraphAPIError as e:
            logger.debug(f"Planner not available: {e}")

        # Test OneDrive access
        try:
            drive = await self.get("/me/drive", token)
            if isinstance(drive, dict) and "id" in drive:
                capabilities["onedrive"]["available"] = True
        except GraphAPIError as e:
            logger.debug(f"OneDrive not available: {e}")

        # Test Teams access
        try:
            teams = await self.get("/me/joinedTeams", token)
            if isinstance(teams, dict) and "value" in teams:
                capabilities["teams"]["available"] = True
        except GraphAPIError as e:
            logger.debug(f"Teams not available: {e}")

        return capabilities
