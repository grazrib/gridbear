"""Pydantic models for Executor API."""

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    """Request to execute a command in a container."""

    project: str = Field(..., description="Project identifier")
    container: str = Field(..., description="Container name")
    command: str = Field(..., description="Command template name or pattern")
    params: dict[str, str] = Field(
        default_factory=dict, description="Parameters for command"
    )
    # E7: Configurable timeout up to 30 minutes (1800s)
    timeout: int = Field(
        default=120, ge=1, le=1800, description="Timeout in seconds (max 30 min)"
    )


class ExecuteResponse(BaseModel):
    """Response from command execution."""

    success: bool
    exit_code: int | None = None
    output: str = ""
    error: str = ""


class ContainerStatus(BaseModel):
    """Container status information."""

    name: str
    status: str
    running: bool
    health: str | None = None


class RestartResponse(BaseModel):
    """Response from container restart."""

    success: bool
    message: str


class AuditEntry(BaseModel):
    """Audit log entry."""

    id: int
    timestamp: str
    project: str
    container: str
    command: str
    user: str
    success: bool
    exit_code: int | None = None
    error: str | None = None
    # E6: Source IP tracking
    source_ip: str | None = None


class HealthResponse(BaseModel):
    """Health check response.

    E8: Enhanced health check with multiple status indicators.
    """

    status: str  # "healthy", "degraded", "unhealthy"
    docker_connected: bool
    config_loaded: bool = True
    audit_db_ok: bool = True
    disk_space_ok: bool = True
    version: str = "1.0.0"


class AuditStats(BaseModel):
    """Audit log statistics."""

    total_entries: int
    success_count: int
    failure_count: int
    oldest_entry: str | None = None
    database_size_bytes: int
    retention_days: int
