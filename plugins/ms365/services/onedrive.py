"""OneDrive service for Microsoft 365 plugin."""

from typing import Any

from config.logging_config import logger

from .graph_client import GraphClient


class OneDriveService:
    """Service for OneDrive operations via Microsoft Graph."""

    def __init__(self, graph_client: GraphClient):
        """Initialize OneDrive service.

        Args:
            graph_client: Graph API client instance
        """
        self.client = graph_client

    async def get_drive(self, token: str) -> dict[str, Any] | None:
        """Get user's OneDrive info.

        Args:
            token: Access token

        Returns:
            Drive info or None
        """
        result = await self.client.get("/me/drive", token)

        if isinstance(result, dict):
            return {
                "id": result.get("id", ""),
                "name": result.get("name", ""),
                "drive_type": result.get("driveType", ""),
                "quota": {
                    "total": result.get("quota", {}).get("total", 0),
                    "used": result.get("quota", {}).get("used", 0),
                    "remaining": result.get("quota", {}).get("remaining", 0),
                },
            }
        return None

    async def list_files(
        self,
        token: str,
        folder_path: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List files in OneDrive folder.

        Args:
            token: Access token
            folder_path: Folder path (root if empty)
            limit: Maximum results

        Returns:
            List of file/folder dicts
        """
        if folder_path and folder_path != "/":
            folder_path = folder_path.strip("/")
            endpoint = f"/me/drive/root:/{folder_path}:/children"
        else:
            endpoint = "/me/drive/root/children"

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
        file_path: str,
    ) -> bytes | None:
        """Read file content from OneDrive.

        Args:
            token: Access token
            file_path: Path to file

        Returns:
            File content as bytes or None
        """
        file_path = file_path.strip("/")
        endpoint = f"/me/drive/root:/{file_path}:/content"

        result = await self.client.get(endpoint, token)
        return result if isinstance(result, bytes) else None

    async def read_file_text(
        self,
        token: str,
        file_path: str,
        encoding: str = "utf-8",
    ) -> str | None:
        """Read file content as text.

        Args:
            token: Access token
            file_path: Path to file
            encoding: Text encoding

        Returns:
            File content as string or None
        """
        content = await self.read_file(token, file_path)
        if content:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                logger.warning(f"Failed to decode file {file_path} as {encoding}")
        return None

    async def write_file(
        self,
        token: str,
        file_path: str,
        content: bytes | str,
    ) -> dict[str, Any] | None:
        """Write/upload file to OneDrive.

        Args:
            token: Access token
            file_path: Path for new/existing file
            content: File content

        Returns:
            Created/updated file info or None
        """
        file_path = file_path.strip("/")
        endpoint = f"/me/drive/root:/{file_path}:/content"

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

    async def delete_file(
        self,
        token: str,
        file_path: str,
    ) -> bool:
        """Delete a file from OneDrive.

        Args:
            token: Access token
            file_path: Path to file

        Returns:
            True if deleted
        """
        file_path = file_path.strip("/")
        endpoint = f"/me/drive/root:/{file_path}"

        try:
            await self.client.delete(endpoint, token)
            return True
        except Exception as e:
            logger.error(f"Failed to delete {file_path}: {e}")
            return False

    async def create_folder(
        self,
        token: str,
        folder_path: str,
    ) -> dict[str, Any] | None:
        """Create a folder in OneDrive.

        Args:
            token: Access token
            folder_path: Path for new folder

        Returns:
            Created folder info or None
        """
        parts = folder_path.strip("/").rsplit("/", 1)
        if len(parts) == 2:
            parent_path, folder_name = parts
            endpoint = f"/me/drive/root:/{parent_path}:/children"
        else:
            folder_name = parts[0]
            endpoint = "/me/drive/root/children"

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

    async def get_file_metadata(
        self,
        token: str,
        file_path: str,
    ) -> dict[str, Any] | None:
        """Get file metadata.

        Args:
            token: Access token
            file_path: Path to file

        Returns:
            File metadata or None
        """
        file_path = file_path.strip("/")
        endpoint = f"/me/drive/root:/{file_path}"

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
            }
        return None

    async def search_files(
        self,
        token: str,
        query: str,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Search files in OneDrive.

        Args:
            token: Access token
            query: Search query
            limit: Maximum results

        Returns:
            List of matching files
        """
        endpoint = f"/me/drive/root/search(q='{query}')"

        result = await self.client.get(endpoint, token, params={"$top": str(limit)})

        if isinstance(result, dict) and "value" in result:
            return [
                {
                    "id": item["id"],
                    "name": item.get("name", ""),
                    "web_url": item.get("webUrl", ""),
                    "type": "folder" if "folder" in item else "file",
                    "size": item.get("size", 0),
                }
                for item in result["value"]
            ]
        return []
