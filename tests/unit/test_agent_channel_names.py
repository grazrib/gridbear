"""Test Agent.get_channel_names() method."""

from unittest.mock import MagicMock


def test_get_channel_names_returns_list():
    """get_channel_names() returns list of channel platform names."""
    from core.agent import Agent

    agent = Agent.__new__(Agent)
    agent._channels = {"telegram": MagicMock(), "discord": MagicMock()}

    result = agent.get_channel_names()

    assert isinstance(result, list)
    assert sorted(result) == ["discord", "telegram"]


def test_get_channel_names_empty():
    """get_channel_names() returns empty list when no channels."""
    from core.agent import Agent

    agent = Agent.__new__(Agent)
    agent._channels = {}

    assert agent.get_channel_names() == []
