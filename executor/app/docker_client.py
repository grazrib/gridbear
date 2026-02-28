"""Docker SDK wrapper for safe container operations.

This module provides a RestrictedDockerClient that only allows specific
safe operations on containers. Dangerous operations are explicitly blocked.

ALLOWED OPERATIONS:
- ping: Check Docker connectivity
- get_container: Get container by name
- get_status: Get container status
- restart_container: Restart a running container
- execute_command: Run a command inside a container

BLOCKED OPERATIONS:
- create: Creating new containers
- pull: Pulling images
- build: Building images
- remove/kill/stop: Removing or stopping containers
- networks: Managing Docker networks
- volumes: Managing Docker volumes
- images: Managing Docker images
"""

import logging

import docker
from docker.errors import APIError, NotFound
from docker.models.containers import Container

from .schemas import ContainerStatus, ExecuteResponse

logger = logging.getLogger(__name__)


class BlockedOperationError(Exception):
    """Raised when a blocked operation is attempted."""

    pass


class RestrictedDockerClient:
    """Restricted wrapper around Docker SDK.

    Only allows safe operations: ping, get, status, restart, exec.
    All other operations are explicitly blocked.
    """

    # List of blocked operation names for audit logging
    BLOCKED_OPERATIONS = frozenset(
        [
            "create",
            "run",
            "pull",
            "build",
            "push",
            "remove",
            "kill",
            "stop",
            "pause",
            "unpause",
            "prune",
            "network",
            "volume",
            "image",
        ]
    )

    def __init__(self):
        """Initialize restricted Docker client."""
        self._client: docker.DockerClient | None = None

    def connect(self) -> bool:
        """Connect to Docker daemon.

        Returns:
            True if connection successful
        """
        try:
            self._client = docker.from_env()
            self._client.ping()
            return True
        except Exception:
            self._client = None
            return False

    @property
    def connected(self) -> bool:
        """Check if connected to Docker."""
        if not self._client:
            return False
        try:
            self._client.ping()
            return True
        except Exception:
            return False

    def get_container(self, name: str) -> Container | None:
        """Get container by name.

        Args:
            name: Container name

        Returns:
            Container object or None if not found
        """
        if not self._client:
            return None
        try:
            return self._client.containers.get(name)
        except NotFound:
            return None

    def get_status(self, name: str) -> ContainerStatus | None:
        """Get container status.

        Args:
            name: Container name

        Returns:
            ContainerStatus or None if not found
        """
        container = self.get_container(name)
        if not container:
            return None

        health = None
        if "Health" in container.attrs.get("State", {}):
            health = container.attrs["State"]["Health"].get("Status")

        return ContainerStatus(
            name=name,
            status=container.status,
            running=container.status == "running",
            health=health,
        )

    def restart_container(self, name: str, timeout: int = 30) -> tuple[bool, str]:
        """Restart a container.

        Args:
            name: Container name
            timeout: Timeout for restart operation

        Returns:
            Tuple of (success, message)
        """
        container = self.get_container(name)
        if not container:
            return False, f"Container '{name}' not found"

        try:
            container.restart(timeout=timeout)
            return True, f"Container '{name}' restarted successfully"
        except APIError as e:
            return False, f"Failed to restart container: {e}"

    def execute_command(
        self, name: str, command: str, timeout: int = 120
    ) -> ExecuteResponse:
        """Execute a command in a container.

        Args:
            name: Container name
            command: Command to execute
            timeout: Command timeout in seconds

        Returns:
            ExecuteResponse with results
        """
        container = self.get_container(name)
        if not container:
            return ExecuteResponse(
                success=False,
                error=f"Container '{name}' not found",
            )

        if container.status != "running":
            return ExecuteResponse(
                success=False,
                error=f"Container '{name}' is not running (status: {container.status})",
            )

        try:
            # Execute command - docker-py exec_run is synchronous
            # Split command properly for exec
            exit_code, output = container.exec_run(
                cmd=command,
                stdout=True,
                stderr=True,
                demux=True,
                environment={"PYTHONUNBUFFERED": "1"},
            )

            stdout = ""
            stderr = ""
            if output[0]:
                stdout = output[0].decode("utf-8", errors="replace")
            if output[1]:
                stderr = output[1].decode("utf-8", errors="replace")

            return ExecuteResponse(
                success=exit_code == 0,
                exit_code=exit_code,
                output=stdout,
                error=stderr,
            )

        except APIError as e:
            return ExecuteResponse(
                success=False,
                error=f"Docker API error: {e}",
            )
        except Exception as e:
            return ExecuteResponse(
                success=False,
                error=f"Execution error: {e}",
            )

    # =========================================================================
    # BLOCKED OPERATIONS - These raise BlockedOperationError
    # =========================================================================

    def _block(self, operation: str) -> None:
        """Block a dangerous operation and log the attempt."""
        logger.warning(f"Blocked operation attempted: {operation}")
        raise BlockedOperationError(
            f"Operation '{operation}' is not allowed by RestrictedDockerClient"
        )

    def create_container(self, *args, **kwargs):
        """BLOCKED: Creating containers is not allowed."""
        self._block("create")

    def run(self, *args, **kwargs):
        """BLOCKED: Running containers is not allowed."""
        self._block("run")

    def pull(self, *args, **kwargs):
        """BLOCKED: Pulling images is not allowed."""
        self._block("pull")

    def build(self, *args, **kwargs):
        """BLOCKED: Building images is not allowed."""
        self._block("build")

    def push(self, *args, **kwargs):
        """BLOCKED: Pushing images is not allowed."""
        self._block("push")

    def remove(self, *args, **kwargs):
        """BLOCKED: Removing containers is not allowed."""
        self._block("remove")

    def kill(self, *args, **kwargs):
        """BLOCKED: Killing containers is not allowed."""
        self._block("kill")

    def stop(self, *args, **kwargs):
        """BLOCKED: Stopping containers is not allowed."""
        self._block("stop")

    def pause(self, *args, **kwargs):
        """BLOCKED: Pausing containers is not allowed."""
        self._block("pause")

    def prune(self, *args, **kwargs):
        """BLOCKED: Pruning is not allowed."""
        self._block("prune")

    def networks(self, *args, **kwargs):
        """BLOCKED: Network management is not allowed."""
        self._block("networks")

    def volumes(self, *args, **kwargs):
        """BLOCKED: Volume management is not allowed."""
        self._block("volumes")

    def images(self, *args, **kwargs):
        """BLOCKED: Image management is not allowed."""
        self._block("images")


# Backward compatibility alias
DockerClient = RestrictedDockerClient

# Singleton instance
_docker_client: RestrictedDockerClient | None = None


def get_docker_client() -> RestrictedDockerClient:
    """Get the restricted Docker client singleton."""
    global _docker_client
    if _docker_client is None:
        _docker_client = RestrictedDockerClient()
        _docker_client.connect()
    return _docker_client
