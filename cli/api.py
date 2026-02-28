"""Sync REST client for the MCP Gateway inspection endpoints."""

import httpx


class APIError(Exception):
    def __init__(self, status: int, message: str, code: str = ""):
        self.status = status
        self.code = code
        super().__init__(message)


class APIClient:
    """REST client for gateway inspection endpoints."""

    def __init__(self, gateway_url: str, token: str):
        self._base = gateway_url
        self._http = httpx.Client(
            timeout=15,
            headers={"Authorization": f"Bearer {token}"},
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        """GET request, parse ApiResponse envelope."""
        resp = self._http.get(f"{self._base}{path}", params=params)

        if resp.status_code == 401:
            raise APIError(401, "Authentication failed")
        if resp.status_code == 403:
            raise APIError(403, "Permission denied")

        data = resp.json()

        if resp.status_code >= 400:
            raise APIError(
                resp.status_code,
                data.get("message", resp.text),
                data.get("code", ""),
            )

        # ApiResponse envelope: {ok, data, ...}
        if isinstance(data, dict) and "ok" in data:
            if not data["ok"]:
                raise APIError(
                    resp.status_code,
                    data.get("message", "Request failed"),
                    data.get("code", ""),
                )
            return data

        return data

    def list_servers(self) -> list[dict]:
        result = self._get("/mcp/servers")
        return result.get("data", [])

    def get_server(self, name: str) -> dict:
        result = self._get(f"/mcp/servers/{name}")
        return result.get("data", {})

    def check_creds(self, connection_id: str, user: str) -> dict:
        result = self._get(f"/mcp/creds/{connection_id}", params={"user": user})
        return result.get("data", {})

    def _post(self, path: str, body: dict) -> dict:
        """POST request, parse ApiResponse envelope."""
        resp = self._http.post(f"{self._base}{path}", json=body, timeout=600)

        if resp.status_code == 401:
            raise APIError(401, "Authentication failed")
        if resp.status_code == 403:
            raise APIError(403, "Permission denied")

        data = resp.json()

        if resp.status_code >= 400:
            raise APIError(
                resp.status_code,
                data.get("message", resp.text),
                data.get("code", ""),
            )

        if isinstance(data, dict) and "ok" in data:
            if not data["ok"]:
                raise APIError(
                    resp.status_code,
                    data.get("message", "Request failed"),
                    data.get("code", ""),
                )
            return data

        return data

    def chat(
        self,
        text: str,
        user_id: str,
        agent_name: str,
        username: str | None = None,
        display_name: str | None = None,
    ) -> dict:
        """Send a chat message via the proxy and return the response."""
        body = {
            "text": text,
            "user_id": user_id,
            "agent_name": agent_name,
            "username": username or user_id,
            "display_name": display_name or "",
        }
        result = self._post("/api/proxy/chat", body)
        return result.get("data", {})

    def close(self):
        self._http.close()
