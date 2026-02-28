"""Custom exceptions for GridBear core."""


class GridBearError(Exception):
    """Base exception for all GridBear errors."""

    pass


class ServiceNotConfiguredError(GridBearError):
    """Raised when an agent requests a service that is not configured."""

    pass


class PluginLoadError(GridBearError):
    """Raised when a plugin fails to load."""

    pass


class AgentStartupError(GridBearError):
    """Raised when an agent fails to start due to missing required service."""

    pass


class AgentNotFoundError(GridBearError):
    """Raised when an agent is not found in the system."""

    pass


class AgentUnavailableError(GridBearError):
    """Raised when an agent exists but is not available (not RUNNING)."""

    pass
