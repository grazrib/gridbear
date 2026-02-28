"""Google Workspace exception hierarchy."""


class GoogleWorkspaceError(Exception):
    """Base exception for Google Workspace operations."""

    def __init__(
        self, message: str, recoverable: bool = False, retry_after: int = None
    ):
        super().__init__(message)
        self.message = message
        self.recoverable = recoverable
        self.retry_after = retry_after


class AuthenticationError(GoogleWorkspaceError):
    """401 - Invalid or expired credentials."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, recoverable=False)


class PermissionError(GoogleWorkspaceError):
    """403 - Insufficient permissions."""

    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, recoverable=False)


class NotFoundError(GoogleWorkspaceError):
    """404 - Resource not found."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, recoverable=False)


class RateLimitError(GoogleWorkspaceError):
    """429 - Rate limit exceeded."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(message, recoverable=True, retry_after=retry_after)


class ValidationError(GoogleWorkspaceError):
    """Invalid input parameters."""

    def __init__(self, message: str = "Invalid input"):
        super().__init__(message, recoverable=False)
