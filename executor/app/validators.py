"""Command whitelist validation for Executor."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandConfig:
    """Configuration for an allowed command."""

    pattern: str
    params: dict[str, str | list[str]]


@dataclass
class ContainerConfig:
    """Configuration for a container."""

    allowed_commands: list[CommandConfig]


@dataclass
class ProjectConfig:
    """Configuration for a project."""

    description: str
    source_path: str
    mount_path: str
    containers: dict[str, ContainerConfig]


class CommandValidator:
    """Validates commands against whitelist configuration."""

    def __init__(self, config_path: str | None = None):
        """Initialize validator with config file.

        Args:
            config_path: Path to executor.json (unified config)
        """
        self._config_path = config_path or os.environ.get(
            "EXECUTOR_CONFIG_PATH", "/app/config/executor.json"
        )
        self._projects: dict[str, ProjectConfig] = {}
        self._load_config()

    def _parse_config(self, data: dict) -> dict[str, ProjectConfig]:
        """Parse config data into ProjectConfig objects.

        Args:
            data: Raw config data from JSON file

        Returns:
            Dict mapping project names to ProjectConfig objects
        """
        projects: dict[str, ProjectConfig] = {}

        for project_name, project_data in data.get("projects", {}).items():
            containers = {}
            for container_name, container_data in project_data.get(
                "containers", {}
            ).items():
                commands = [
                    CommandConfig(
                        pattern=cmd["pattern"],
                        params=cmd.get("params", {}),
                    )
                    for cmd in container_data.get("allowed_commands", [])
                ]
                containers[container_name] = ContainerConfig(allowed_commands=commands)

            projects[project_name] = ProjectConfig(
                description=project_data.get("description", ""),
                source_path=project_data.get("source_path", ""),
                mount_path=project_data.get("mount_path", ""),
                containers=containers,
            )

        return projects

    def _load_config(self) -> None:
        """Load configuration from file."""
        path = Path(self._config_path)
        if not path.exists():
            raise RuntimeError(f"Config file not found: {self._config_path}")

        with open(path) as f:
            data = json.load(f)

        self._projects = self._parse_config(data)

    def reload_config(self) -> None:
        """Reload configuration from file - atomic replacement.

        Thread-safe: no window where _projects is empty or inconsistent.
        """
        path = Path(self._config_path)
        if not path.exists():
            raise RuntimeError(f"Config file not found: {self._config_path}")

        with open(path) as f:
            data = json.load(f)

        # Atomic replacement - no clear()
        self._projects = self._parse_config(data)

    def get_project(self, project: str) -> ProjectConfig | None:
        """Get project configuration."""
        return self._projects.get(project)

    def list_projects(self) -> list[str]:
        """List all configured projects."""
        return list(self._projects.keys())

    def validate_and_build_command(
        self, project: str, container: str, command: str, params: dict[str, str]
    ) -> tuple[bool, str, str]:
        """Validate command and build the actual command string.

        Args:
            project: Project identifier
            container: Container name
            command: Command pattern or name
            params: Parameters for the command

        Returns:
            Tuple of (is_valid, built_command, error_message)
        """
        project_config = self._projects.get(project)
        if not project_config:
            return False, "", f"Project '{project}' not configured"

        container_config = project_config.containers.get(container)
        if not container_config:
            return (
                False,
                "",
                f"Container '{container}' not allowed for project '{project}'",
            )

        # Find matching command pattern
        for cmd_config in container_config.allowed_commands:
            # Handle special "restart" command
            if cmd_config.pattern == "restart" and command == "restart":
                return True, "RESTART", ""

            # Check if command matches pattern
            built, error = self._match_and_build(cmd_config, command, params)
            if built:
                return True, built, ""

        return False, "", f"Command not in whitelist for container '{container}'"

    def _match_and_build(
        self, cmd_config: CommandConfig, command: str, params: dict[str, str]
    ) -> tuple[str | None, str]:
        """Try to match command against pattern and build final command.

        Supports two modes:
        1. Full command matching: Extract params from command by matching pattern
        2. Pattern + params: Use provided params to build command

        Args:
            cmd_config: Command configuration
            command: Input command (can be full command or pattern)
            params: Parameters (can be empty if command is full)

        Returns:
            Tuple of (built_command or None, error_message)
        """
        pattern = cmd_config.pattern

        # If command is exactly the pattern (no params), direct match
        if command == pattern and not params and not cmd_config.params:
            return pattern, ""

        # Find all {param} placeholders in pattern
        placeholders = re.findall(r"\{(\w+)\}", pattern)

        if not placeholders and command == pattern:
            return pattern, ""

        if not placeholders:
            return None, "Pattern mismatch"

        # If params not provided, try to extract them from command
        if not params:
            extracted = self._extract_params_from_command(
                pattern, command, placeholders
            )
            if extracted is None:
                return None, "Command does not match pattern"
            params = extracted

        # Check all required params are provided
        for placeholder in placeholders:
            if placeholder not in params:
                return None, f"Missing parameter: {placeholder}"

        # Validate each parameter
        for placeholder in placeholders:
            value = params[placeholder]
            param_rule = cmd_config.params.get(placeholder)

            if param_rule is None:
                return None, f"No validation rule for parameter: {placeholder}"

            # Validate against rule
            if isinstance(param_rule, list):
                # Must be one of allowed values
                if value not in param_rule:
                    return (
                        None,
                        f"Parameter '{placeholder}' must be one of: {param_rule}",
                    )
            elif isinstance(param_rule, str):
                # Must match regex pattern
                if not re.match(f"^{param_rule}$", value):
                    return (
                        None,
                        f"Parameter '{placeholder}' does not match pattern: {param_rule}",
                    )

        # Build the command by substituting parameters
        result = pattern
        for placeholder in placeholders:
            result = result.replace(f"{{{placeholder}}}", params[placeholder])

        return result, ""

    def _extract_params_from_command(
        self, pattern: str, command: str, placeholders: list[str]
    ) -> dict[str, str] | None:
        """Extract parameter values from a full command by matching against pattern.

        Args:
            pattern: Pattern with {placeholder} markers
            command: Full command string
            placeholders: List of placeholder names

        Returns:
            Dict of extracted params, or None if command doesn't match pattern
        """
        # Convert pattern to regex, escaping special chars and replacing placeholders
        regex_pattern = re.escape(pattern)
        for placeholder in placeholders:
            # Replace escaped placeholder with capture group
            regex_pattern = regex_pattern.replace(
                re.escape(f"{{{placeholder}}}"), f"(?P<{placeholder}>.+?)"
            )

        # Try to match
        match = re.fullmatch(regex_pattern, command)
        if not match:
            return None

        return match.groupdict()


# Singleton instance
_validator: CommandValidator | None = None


def get_validator() -> CommandValidator:
    """Get the command validator singleton."""
    global _validator
    if _validator is None:
        _validator = CommandValidator()
    return _validator
