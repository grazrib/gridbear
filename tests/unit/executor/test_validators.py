"""Tests for executor command validators."""

import json
import os
import tempfile
import threading
import time

import pytest

from executor.app.validators import CommandValidator


@pytest.fixture
def config_file():
    """Create a temporary config file, cleaned up after test."""
    config = {
        "projects": {
            "test_project": {
                "description": "Test Project",
                "source_path": "/test/path",
                "mount_path": "/projects/test",
                "containers": {
                    "test_container": {
                        "allowed_commands": [
                            {
                                "pattern": "echo {msg}",
                                "params": {"msg": "^[a-z]+$"},
                            },
                            {"pattern": "restart", "params": {}},
                        ]
                    }
                },
            }
        }
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def validator(config_file):
    """Create a CommandValidator instance."""
    return CommandValidator(config_path=config_file)


class TestCommandValidator:
    """Tests for CommandValidator."""

    def test_load_config(self, validator):
        """Test that config is loaded correctly."""
        projects = validator.list_projects()
        assert "test_project" in projects

    def test_get_project(self, validator):
        """Test getting a project config."""
        project = validator.get_project("test_project")
        assert project is not None
        assert project.description == "Test Project"
        assert "test_container" in project.containers

    def test_get_project_not_found(self, validator):
        """Test getting a non-existent project."""
        project = validator.get_project("nonexistent")
        assert project is None

    def test_validate_command_success(self, validator):
        """Test successful command validation."""
        is_valid, built, error = validator.validate_and_build_command(
            "test_project", "test_container", "echo {msg}", {"msg": "hello"}
        )
        assert is_valid
        assert built == "echo hello"
        assert error == ""

    def test_validate_command_restart(self, validator):
        """Test restart command validation."""
        is_valid, built, error = validator.validate_and_build_command(
            "test_project", "test_container", "restart", {}
        )
        assert is_valid
        assert built == "RESTART"

    def test_validate_command_invalid_param(self, validator):
        """Test command validation with invalid parameter."""
        is_valid, built, error = validator.validate_and_build_command(
            "test_project", "test_container", "echo {msg}", {"msg": "INVALID123"}
        )
        assert not is_valid
        assert "not in whitelist" in error

    def test_validate_command_project_not_found(self, validator):
        """Test command validation with non-existent project."""
        is_valid, built, error = validator.validate_and_build_command(
            "nonexistent", "test_container", "echo {msg}", {"msg": "hello"}
        )
        assert not is_valid
        assert "not configured" in error

    def test_validate_command_container_not_found(self, validator):
        """Test command validation with non-existent container."""
        is_valid, built, error = validator.validate_and_build_command(
            "test_project", "nonexistent", "echo {msg}", {"msg": "hello"}
        )
        assert not is_valid
        assert "not allowed" in error

    def test_validate_command_not_in_whitelist(self, validator):
        """Test command validation with non-whitelisted command."""
        is_valid, built, error = validator.validate_and_build_command(
            "test_project", "test_container", "rm -rf /", {}
        )
        assert not is_valid
        assert "not in whitelist" in error


class TestReloadConfigAtomic:
    """Tests for atomic config reload (race condition fix)."""

    def test_reload_config_updates_projects(self, config_file):
        """Test that reload_config updates the projects."""
        validator = CommandValidator(config_path=config_file)
        assert "test_project" in validator.list_projects()

        # Update config file
        new_config = {
            "projects": {
                "new_project": {
                    "description": "New Project",
                    "source_path": "/new/path",
                    "mount_path": "/projects/new",
                    "containers": {},
                }
            }
        }
        with open(config_file, "w") as f:
            json.dump(new_config, f)

        # Reload
        validator.reload_config()

        # Check new config is loaded
        assert "new_project" in validator.list_projects()
        assert "test_project" not in validator.list_projects()

    def test_reload_config_atomic_no_empty_window(self, config_file):
        """Test that reload_config has no window where projects is empty.

        This test verifies the race condition fix: during reload, there
        should never be a moment where _projects is empty.
        """
        validator = CommandValidator(config_path=config_file)
        errors = []
        stop_event = threading.Event()

        def reader():
            """Continuously read projects, looking for empty dict."""
            while not stop_event.is_set():
                projects = validator.list_projects()
                if len(projects) == 0:
                    errors.append("Projects was empty!")
                time.sleep(0.0001)  # Small delay

        def reloader():
            """Continuously reload config."""
            for _ in range(100):
                if stop_event.is_set():
                    break
                validator.reload_config()
                time.sleep(0.001)

        # Start reader threads
        readers = [threading.Thread(target=reader) for _ in range(5)]
        for r in readers:
            r.start()

        # Start reloader
        reloader_thread = threading.Thread(target=reloader)
        reloader_thread.start()

        # Wait for reloader to finish
        reloader_thread.join()

        # Stop readers
        stop_event.set()
        for r in readers:
            r.join()

        # Check no errors
        assert len(errors) == 0, f"Race condition detected: {errors}"

    def test_reload_config_concurrent_validation(self, config_file):
        """Test that validation works correctly during reload.

        Commands being validated during a reload should either use
        the old config or the new config, but never fail due to
        empty/inconsistent state.
        """
        validator = CommandValidator(config_path=config_file)
        errors = []
        stop_event = threading.Event()

        def validator_thread():
            """Continuously validate commands."""
            while not stop_event.is_set():
                try:
                    is_valid, built, error = validator.validate_and_build_command(
                        "test_project", "test_container", "restart", {}
                    )
                    # Should either succeed or fail with "not configured"
                    # (if config was just reloaded with different projects)
                    # But should NEVER fail with unexpected error
                    if not is_valid and "not configured" not in error:
                        errors.append(f"Unexpected error: {error}")
                except Exception as e:
                    errors.append(f"Exception: {e}")
                time.sleep(0.0001)

        def reloader():
            """Continuously reload config."""
            for _ in range(50):
                if stop_event.is_set():
                    break
                validator.reload_config()
                time.sleep(0.002)

        # Start validator threads
        validators = [threading.Thread(target=validator_thread) for _ in range(3)]
        for v in validators:
            v.start()

        # Start reloader
        reloader_thread = threading.Thread(target=reloader)
        reloader_thread.start()

        # Wait for reloader to finish
        reloader_thread.join()

        # Stop validators
        stop_event.set()
        for v in validators:
            v.join()

        # Check no unexpected errors
        assert len(errors) == 0, f"Errors during concurrent access: {errors}"
