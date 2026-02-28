"""Sync JSON-RPC 2.0 client for the MCP Gateway."""

import itertools

import httpx


class GatewayError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


_id_counter = itertools.count(1)


class GatewayClient:
    """MCP Gateway JSON-RPC client (synchronous)."""

    def __init__(self, gateway_url: str, token: str):
        self._url = f"{gateway_url}/mcp"
        self._http = httpx.Client(
            timeout=30,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        self._session_id: str | None = None

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC 2.0 request and return the result."""
        payload = {
            "jsonrpc": "2.0",
            "id": next(_id_counter),
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        headers = {}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        resp = self._http.post(self._url, json=payload, headers=headers)

        # Capture session ID from response
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid

        if resp.status_code == 401:
            raise GatewayError(-32001, "Authentication failed (401)")
        if resp.status_code == 403:
            raise GatewayError(-32002, "Permission denied (403)")

        data = resp.json()
        if "error" in data:
            err = data["error"]
            raise GatewayError(err.get("code", -1), err.get("message", "Unknown"))

        return data.get("result", {})

    def initialize(self) -> dict:
        """Initialize MCP session."""
        return self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "gridbear-cli", "version": "0.1.0"},
            },
        )

    def list_tools(self, user_identity: str | None = None) -> list[dict]:
        """List available tools, optionally for a specific user."""
        params = {}
        if user_identity:
            params["_meta"] = {"user_identity": user_identity}
        result = self._rpc("tools/list", params or None)
        return result.get("tools", [])

    def call_tool(
        self, name: str, arguments: dict | None = None, user_identity: str | None = None
    ) -> list[dict]:
        """Call a tool and return content blocks."""
        params = {"name": name}
        if arguments:
            params["arguments"] = arguments
        if user_identity:
            if "_meta" not in params:
                params["_meta"] = {}
            params["_meta"]["user_identity"] = user_identity
        result = self._rpc("tools/call", params)
        return result.get("content", [])

    def set_user_context(self, gateway_url: str, user_identity: str):
        """Set user context via side-channel endpoint."""
        resp = self._http.post(
            f"{gateway_url}/mcp/user-context",
            json={"user_identity": user_identity},
        )
        if resp.status_code != 200:
            raise GatewayError(-32003, f"Failed to set user context: {resp.text}")

    def close(self):
        self._http.close()
