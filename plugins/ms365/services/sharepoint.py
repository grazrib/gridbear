"""SharePoint service for Microsoft 365 plugin."""

from typing import Any

from config.logging_config import logger

from .graph_client import GraphClient


class SharePointService:
    """Service for SharePoint operations via Microsoft Graph."""

    def __init__(self, graph_client: GraphClient):
        """Initialize SharePoint service.

        Args:
            graph_client: Graph API client instance
        """
        self.client = graph_client

    async def list_sites(
        self,
        token: str,
        search: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List accessible SharePoint sites.

        Args:
            token: Access token
            search: Optional search query
            limit: Maximum results

        Returns:
            List of site dicts
        """
        if search:
            endpoint = f"/sites?search={search}"
        else:
            endpoint = "/sites?search=*"

        result = await self.client.get(endpoint, token, params={"$top": str(limit)})

        if isinstance(result, dict) and "value" in result:
            return [
                {
                    "id": site["id"],
                    "name": site.get("displayName", site.get("name", "")),
                    "web_url": site.get("webUrl", ""),
                    "description": site.get("description", ""),
                }
                for site in result["value"]
            ]
        return []

    async def get_site(self, token: str, site_id: str) -> dict[str, Any] | None:
        """Get site details.

        Args:
            token: Access token
            site_id: Site ID

        Returns:
            Site details or None
        """
        result = await self.client.get(f"/sites/{site_id}", token)
        if isinstance(result, dict):
            return {
                "id": result["id"],
                "name": result.get("displayName", result.get("name", "")),
                "web_url": result.get("webUrl", ""),
                "description": result.get("description", ""),
            }
        return None

    async def list_drives(self, token: str, site_id: str) -> list[dict[str, Any]]:
        """List document libraries (drives) in a site.

        Args:
            token: Access token
            site_id: Site ID

        Returns:
            List of drive dicts
        """
        result = await self.client.get(f"/sites/{site_id}/drives", token)

        if isinstance(result, dict) and "value" in result:
            return [
                {
                    "id": drive["id"],
                    "name": drive.get("name", ""),
                    "web_url": drive.get("webUrl", ""),
                    "drive_type": drive.get("driveType", ""),
                }
                for drive in result["value"]
            ]
        return []

    async def list_files(
        self,
        token: str,
        site_id: str,
        drive_id: str | None = None,
        folder_path: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List files in a SharePoint folder.

        Args:
            token: Access token
            site_id: Site ID
            drive_id: Drive ID (uses default if not specified)
            folder_path: Folder path (root if empty)
            limit: Maximum results

        Returns:
            List of file/folder dicts
        """
        # Get default drive if not specified
        if not drive_id:
            drives = await self.list_drives(token, site_id)
            if not drives:
                return []
            drive_id = drives[0]["id"]

        # Build endpoint
        if folder_path and folder_path != "/":
            folder_path = folder_path.strip("/")
            endpoint = (
                f"/sites/{site_id}/drives/{drive_id}/root:/{folder_path}:/children"
            )
        else:
            endpoint = f"/sites/{site_id}/drives/{drive_id}/root/children"

        result = await self.client.get(endpoint, token, params={"$top": str(limit)})

        if isinstance(result, dict) and "value" in result:
            return [
                {
                    "id": item["id"],
                    "name": item.get("name", ""),
                    "type": "folder" if "folder" in item else "file",
                    "size": item.get("size", 0),
                    "web_url": item.get("webUrl", ""),
                    "last_modified": item.get("lastModifiedDateTime", ""),
                    "mime_type": item.get("file", {}).get("mimeType", ""),
                }
                for item in result["value"]
            ]
        return []

    async def read_file(
        self,
        token: str,
        site_id: str,
        file_path: str,
        drive_id: str | None = None,
    ) -> bytes | None:
        """Read file content from SharePoint.

        Args:
            token: Access token
            site_id: Site ID
            file_path: Path to file
            drive_id: Drive ID (uses default if not specified)

        Returns:
            File content as bytes or None
        """
        if not drive_id:
            drives = await self.list_drives(token, site_id)
            if not drives:
                return None
            drive_id = drives[0]["id"]

        file_path = file_path.strip("/")
        endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{file_path}:/content"

        result = await self.client.get(endpoint, token)
        return result if isinstance(result, bytes) else None

    async def read_file_text(
        self,
        token: str,
        site_id: str,
        file_path: str,
        drive_id: str | None = None,
        encoding: str = "utf-8",
    ) -> str | None:
        """Read file content as text.

        Args:
            token: Access token
            site_id: Site ID
            file_path: Path to file
            drive_id: Drive ID
            encoding: Text encoding

        Returns:
            File content as string or None
        """
        content = await self.read_file(token, site_id, file_path, drive_id)
        if content:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                logger.warning(f"Failed to decode file {file_path} as {encoding}")
        return None

    async def write_file(
        self,
        token: str,
        site_id: str,
        file_path: str,
        content: bytes | str,
        drive_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Write/upload file to SharePoint.

        Args:
            token: Access token
            site_id: Site ID
            file_path: Path for new/existing file
            content: File content
            drive_id: Drive ID

        Returns:
            Created/updated file info or None
        """
        if not drive_id:
            drives = await self.list_drives(token, site_id)
            if not drives:
                return None
            drive_id = drives[0]["id"]

        file_path = file_path.strip("/")
        endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{file_path}:/content"

        # Convert string to bytes
        if isinstance(content, str):
            content = content.encode("utf-8")

        result = await self.client.put(
            endpoint,
            token,
            data=content,
            content_type="application/octet-stream",
        )

        if isinstance(result, dict):
            return {
                "id": result.get("id", ""),
                "name": result.get("name", ""),
                "web_url": result.get("webUrl", ""),
                "size": result.get("size", 0),
            }
        return None

    async def search_files(
        self,
        token: str,
        query: str,
        site_id: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Search for files across SharePoint.

        Args:
            token: Access token
            query: Search query
            site_id: Limit search to specific site
            limit: Maximum results

        Returns:
            List of matching file dicts
        """
        if site_id:
            endpoint = f"/sites/{site_id}/drive/root/search(q='{query}')"
        else:
            # Search across all sites (requires Sites.Read.All)
            endpoint = "/search/query"
            # Use search API
            body = {
                "requests": [
                    {
                        "entityTypes": ["driveItem"],
                        "query": {"queryString": query},
                        "from": 0,
                        "size": limit,
                    }
                ]
            }
            result = await self.client.post(endpoint, token, json_data=body)

            if isinstance(result, dict) and "value" in result:
                hits = result["value"][0].get("hitsContainers", [{}])[0].get("hits", [])
                return [
                    {
                        "id": hit.get("resource", {}).get("id", ""),
                        "name": hit.get("resource", {}).get("name", ""),
                        "web_url": hit.get("resource", {}).get("webUrl", ""),
                        "summary": hit.get("summary", ""),
                    }
                    for hit in hits
                ]
            return []

        # Simple site-scoped search
        result = await self.client.get(endpoint, token, params={"$top": str(limit)})

        if isinstance(result, dict) and "value" in result:
            return [
                {
                    "id": item["id"],
                    "name": item.get("name", ""),
                    "web_url": item.get("webUrl", ""),
                    "type": "folder" if "folder" in item else "file",
                }
                for item in result["value"]
            ]
        return []

    async def get_file_metadata(
        self,
        token: str,
        site_id: str,
        file_path: str,
        drive_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Get file metadata without downloading content.

        Args:
            token: Access token
            site_id: Site ID
            file_path: Path to file
            drive_id: Drive ID

        Returns:
            File metadata or None
        """
        if not drive_id:
            drives = await self.list_drives(token, site_id)
            if not drives:
                return None
            drive_id = drives[0]["id"]

        file_path = file_path.strip("/")
        endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{file_path}"

        result = await self.client.get(endpoint, token)

        if isinstance(result, dict):
            return {
                "id": result.get("id", ""),
                "name": result.get("name", ""),
                "size": result.get("size", 0),
                "web_url": result.get("webUrl", ""),
                "mime_type": result.get("file", {}).get("mimeType", ""),
                "created": result.get("createdDateTime", ""),
                "modified": result.get("lastModifiedDateTime", ""),
                "created_by": result.get("createdBy", {})
                .get("user", {})
                .get("displayName", ""),
                "modified_by": result.get("lastModifiedBy", {})
                .get("user", {})
                .get("displayName", ""),
            }
        return None

    async def create_folder(
        self,
        token: str,
        site_id: str,
        folder_path: str,
        drive_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Create a folder in SharePoint.

        Args:
            token: Access token
            site_id: Site ID
            folder_path: Path for new folder
            drive_id: Drive ID

        Returns:
            Created folder info or None
        """
        if not drive_id:
            drives = await self.list_drives(token, site_id)
            if not drives:
                return None
            drive_id = drives[0]["id"]

        # Split path into parent and name
        parts = folder_path.strip("/").rsplit("/", 1)
        if len(parts) == 2:
            parent_path, folder_name = parts
            endpoint = (
                f"/sites/{site_id}/drives/{drive_id}/root:/{parent_path}:/children"
            )
        else:
            folder_name = parts[0]
            endpoint = f"/sites/{site_id}/drives/{drive_id}/root/children"

        result = await self.client.post(
            endpoint,
            token,
            json_data={
                "name": folder_name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail",
            },
        )

        if isinstance(result, dict):
            return {
                "id": result.get("id", ""),
                "name": result.get("name", ""),
                "web_url": result.get("webUrl", ""),
            }
        return None
