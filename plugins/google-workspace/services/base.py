"""Base service for Google Workspace API operations."""

from exceptions import (
    AuthenticationError,
    GoogleWorkspaceError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    ValidationError,
)
from googleapiclient.errors import HttpError


class BaseGoogleService:
    """Base class for Google Workspace services."""

    def _handle_api_error(self, error: HttpError) -> GoogleWorkspaceError:
        """Convert Google API HttpError to custom exception.

        Args:
            error: The HttpError from Google API

        Returns:
            Appropriate GoogleWorkspaceError subclass
        """
        status = error.resp.status
        message = str(error)

        if status == 401:
            return AuthenticationError(message)
        elif status == 403:
            return PermissionError(message)
        elif status == 404:
            return NotFoundError(message)
        elif status == 429:
            retry_after = error.resp.get("Retry-After", 60)
            try:
                retry_after = int(retry_after)
            except (ValueError, TypeError):
                retry_after = 60
            return RateLimitError(message, retry_after=retry_after)
        elif status == 400:
            return ValidationError(message)
        else:
            return GoogleWorkspaceError(message)

    def _format_response(
        self,
        data: dict = None,
        success: bool = True,
        error: str = None,
        recoverable: bool = False,
        retry_after: int = None,
    ) -> dict:
        """Format standard response.

        Args:
            data: Response data
            success: Whether operation succeeded
            error: Error message if failed
            recoverable: Whether error is recoverable
            retry_after: Seconds to wait before retry

        Returns:
            Formatted response dict
        """
        return {
            "success": success,
            "data": data,
            "error": error,
            "recoverable": recoverable,
            "retry_after": retry_after,
        }

    def _format_error(self, exc) -> dict:
        """Format error response from exception or string.

        Args:
            exc: The GoogleWorkspaceError exception or error string

        Returns:
            Formatted error response
        """
        if isinstance(exc, str):
            return self._format_response(
                success=False,
                error=exc,
                recoverable=False,
                retry_after=None,
            )
        return self._format_response(
            success=False,
            error=exc.message,
            recoverable=exc.recoverable,
            retry_after=exc.retry_after,
        )
