"""Executor API - Secure Docker command execution."""

import logging

from fastapi import FastAPI, HTTPException, Query, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .audit import get_audit_log
from .auth import TokenDep, TokenResponse, create_jwt_token, revoke_token
from .docker_client import get_docker_client
from .schemas import (
    AuditEntry,
    AuditStats,
    ContainerStatus,
    ExecuteRequest,
    ExecuteResponse,
    HealthResponse,
    RestartResponse,
)
from .validators import get_validator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rate limiter - uses client IP
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="GridBear Executor",
    description="Secure Docker command execution API",
    version="1.0.0",
)

# Add rate limit exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.on_event("startup")
async def startup():
    """Initialize services on startup."""
    docker = get_docker_client()
    if not docker.connected:
        logger.error("Failed to connect to Docker daemon")
    else:
        logger.info("Connected to Docker daemon")

    try:
        validator = get_validator()
        logger.info(f"Loaded config for projects: {validator.list_projects()}")
    except Exception as e:
        logger.error(f"Failed to load validator config: {e}")


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """E8: Enhanced health check endpoint.

    Checks:
    - Docker daemon connectivity
    - Configuration loaded
    - Audit database accessible
    - Disk space available
    """
    import shutil
    from pathlib import Path

    docker = get_docker_client()
    audit = get_audit_log()

    # Check Docker
    docker_ok = docker.connected

    # Check config
    try:
        validator = get_validator()
        config_ok = len(validator.list_projects()) >= 0
    except Exception:
        config_ok = False

    # Check audit DB
    try:
        audit.get_stats()
        audit_ok = True
    except Exception:
        audit_ok = False

    # Check disk space (warn if < 100MB free)
    try:
        data_path = Path("/app/data")
        if data_path.exists():
            usage = shutil.disk_usage(data_path)
            disk_ok = usage.free > 100 * 1024 * 1024  # 100MB
        else:
            disk_ok = True
    except Exception:
        disk_ok = True  # Don't fail health on disk check error

    # Determine overall status
    if docker_ok and config_ok and audit_ok and disk_ok:
        status = "healthy"
    elif docker_ok:
        status = "degraded"
    else:
        status = "unhealthy"

    return HealthResponse(
        status=status,
        docker_connected=docker_ok,
        config_loaded=config_ok,
        audit_db_ok=audit_ok,
        disk_space_ok=disk_ok,
    )


# =============================================================================
# E1: JWT Authentication endpoints
# =============================================================================


@app.post("/auth/token", response_model=TokenResponse)
@limiter.limit("10/minute")
async def get_token(
    request: Request,
    token: TokenDep,
) -> TokenResponse:
    """Get a new JWT token.

    Requires authentication with either:
    - Static EXECUTOR_AUTH_TOKEN (bootstrap)
    - Valid JWT token (refresh)
    """
    # Use the subject from current token if JWT, otherwise use "gridbear"
    subject = token.sub if token.sub != "bootstrap" else "gridbear"
    return create_jwt_token(subject=subject)


@app.post("/auth/revoke")
@limiter.limit("10/minute")
async def revoke_current_token(
    request: Request,
    token: TokenDep,
) -> dict:
    """Revoke the current JWT token.

    The token will be added to a blacklist and rejected on future requests.
    Static bootstrap tokens cannot be revoked.
    """
    if token.jti == "static":
        raise HTTPException(
            status_code=400,
            detail="Cannot revoke static bootstrap token",
        )

    revoke_token(token.jti, token.exp)
    return {"success": True, "message": "Token revoked"}


@app.post("/execute", response_model=ExecuteResponse)
@limiter.limit("30/minute")
async def execute_command(
    request: Request,
    body: ExecuteRequest,
    token: TokenDep,
) -> ExecuteResponse:
    """Execute a validated command in a container.

    The command must match a whitelisted pattern for the project/container.
    All parameters are validated against their rules.
    """
    validator = get_validator()
    docker = get_docker_client()
    audit = get_audit_log()

    # Validate command against whitelist
    is_valid, built_command, error = validator.validate_and_build_command(
        project=body.project,
        container=body.container,
        command=body.command,
        params=body.params,
    )

    # E6: Get client IP for audit logging
    client_ip = get_remote_address(request)

    if not is_valid:
        logger.warning(
            f"Rejected command: project={body.project}, "
            f"container={body.container}, command={body.command}, "
            f"reason={error}"
        )
        audit.log(
            project=body.project,
            container=body.container,
            command=body.command,
            user=token.sub,
            success=False,
            error=f"Validation failed: {error}",
            source_ip=client_ip,
        )
        raise HTTPException(status_code=403, detail=error)

    # Handle special restart command
    if built_command == "RESTART":
        success, message = docker.restart_container(body.container)
        audit.log(
            project=body.project,
            container=body.container,
            command="restart",
            user=token.sub,
            success=success,
            error=None if success else message,
            source_ip=client_ip,
        )
        return ExecuteResponse(
            success=success,
            output=message if success else "",
            error="" if success else message,
        )

    # Execute the command
    logger.info(f"Executing: container={body.container}, command={built_command}")

    result = docker.execute_command(
        name=body.container,
        command=built_command,
        timeout=body.timeout,
    )

    # Log to audit
    audit.log(
        project=body.project,
        container=body.container,
        command=built_command,
        user=token.sub,
        success=result.success,
        exit_code=result.exit_code,
        error=result.error if not result.success else None,
        source_ip=client_ip,
    )

    return result


@app.get("/containers/{name}/status", response_model=ContainerStatus)
@limiter.limit("60/minute")
async def get_container_status(
    request: Request,
    name: str,
    token: TokenDep,
) -> ContainerStatus:
    """Get container status."""
    docker = get_docker_client()
    status = docker.get_status(name)

    if not status:
        raise HTTPException(status_code=404, detail=f"Container '{name}' not found")

    return status


@app.post("/containers/{name}/restart", response_model=RestartResponse)
@limiter.limit("5/minute")
async def restart_container(
    request: Request,
    name: str,
    project: str,
    token: TokenDep,
) -> RestartResponse:
    """Restart a container.

    Container must be in the project's whitelist with restart allowed.
    """
    validator = get_validator()
    docker = get_docker_client()
    audit = get_audit_log()

    # E6: Get client IP for audit logging
    client_ip = get_remote_address(request)

    # Validate container is allowed for project
    is_valid, _, error = validator.validate_and_build_command(
        project=project,
        container=name,
        command="restart",
        params={},
    )

    if not is_valid:
        audit.log(
            project=project,
            container=name,
            command="restart",
            user=token.sub,
            success=False,
            error=f"Not allowed: {error}",
            source_ip=client_ip,
        )
        raise HTTPException(status_code=403, detail=error)

    success, message = docker.restart_container(name)

    audit.log(
        project=project,
        container=name,
        command="restart",
        user=token.sub,
        success=success,
        error=None if success else message,
        source_ip=client_ip,
    )

    return RestartResponse(success=success, message=message)


@app.get("/audit", response_model=list[AuditEntry])
@limiter.limit("30/minute")
async def query_audit_log(
    request: Request,
    token: TokenDep,
    project: str | None = Query(None),
    container: str | None = Query(None),
    user: str | None = Query(None),
    success: bool | None = Query(None),
    source_ip: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[AuditEntry]:
    """Query the audit log."""
    audit = get_audit_log()
    return audit.query(
        project=project,
        container=container,
        user=user,
        success=success,
        source_ip=source_ip,
        limit=limit,
        offset=offset,
    )


@app.get("/audit/stats", response_model=AuditStats)
@limiter.limit("30/minute")
async def get_audit_stats(
    request: Request,
    token: TokenDep,
) -> AuditStats:
    """E6: Get audit log statistics."""
    audit = get_audit_log()
    stats = audit.get_stats()
    return AuditStats(**stats)


@app.post("/config/reload")
@limiter.limit("5/minute")
async def reload_config(request: Request, token: TokenDep) -> dict:
    """Reload the validator configuration."""
    validator = get_validator()
    try:
        validator.reload_config()
        return {"success": True, "projects": validator.list_projects()}
    except Exception as e:
        logger.error(f"Config reload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to reload configuration")
