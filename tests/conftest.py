"""Shared fixtures for GridBear tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_config():
    """Mock ConfigManager for isolated tests."""
    config = MagicMock()
    config.get.return_value = {}
    config.get_channel_users.return_value = {"ids": [], "usernames": []}
    config.get_user_identities.return_value = {}
    return config


@pytest.fixture
def mock_secrets():
    """Mock SecretsManager for isolated tests."""
    secrets = MagicMock()
    secrets.get.return_value = "test-secret-value"
    secrets.set.return_value = None
    return secrets


@pytest.fixture
async def mock_httpx_client():
    """Mock httpx.AsyncClient for tests without network."""
    client = AsyncMock()
    client.get.return_value = AsyncMock(status_code=200, json=lambda: {})
    client.post.return_value = AsyncMock(status_code=200, json=lambda: {})
    return client
