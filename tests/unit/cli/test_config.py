"""Tests for CLI config loading — precedence, env override, TOML."""

import os
from unittest.mock import patch

from cli.config import DEFAULT_GATEWAY_URL, load_config


class TestConfigPrecedence:
    """Config precedence: overrides > env > TOML > defaults."""

    def test_defaults(self):
        with (
            patch("cli.config._load_toml", return_value={}),
            patch.dict(os.environ, {}, clear=True),
        ):
            cfg = load_config()
        assert cfg.gateway_url == DEFAULT_GATEWAY_URL
        assert cfg.default_user is None
        assert cfg.default_agent is None

    def test_toml_values(self):
        toml_data = {
            "connection": {
                "gateway_url": "http://toml:9999",
                "default_user": "toml-user",
                "default_agent": "toml-agent",
            }
        }
        with (
            patch("cli.config._load_toml", return_value=toml_data),
            patch.dict(os.environ, {}, clear=True),
        ):
            cfg = load_config()
        assert cfg.gateway_url == "http://toml:9999"
        assert cfg.default_user == "toml-user"
        assert cfg.default_agent == "toml-agent"

    def test_env_overrides_toml(self):
        toml_data = {
            "connection": {
                "gateway_url": "http://toml:9999",
                "default_user": "toml-user",
            }
        }
        env = {
            "GRIDBEAR_GATEWAY_URL": "http://env:8888",
            "GRIDBEAR_CLI_USER": "env-user",
        }
        with (
            patch("cli.config._load_toml", return_value=toml_data),
            patch.dict(os.environ, env, clear=True),
        ):
            cfg = load_config()
        assert cfg.gateway_url == "http://env:8888"
        assert cfg.default_user == "env-user"

    def test_overrides_win(self):
        env = {"GRIDBEAR_GATEWAY_URL": "http://env:8888"}
        with (
            patch("cli.config._load_toml", return_value={}),
            patch.dict(os.environ, env, clear=True),
        ):
            cfg = load_config(gateway_url="http://override:7777")
        assert cfg.gateway_url == "http://override:7777"

    def test_trailing_slash_stripped(self):
        with (
            patch("cli.config._load_toml", return_value={}),
            patch.dict(os.environ, {}, clear=True),
        ):
            cfg = load_config(gateway_url="http://localhost:8088/")
        assert cfg.gateway_url == "http://localhost:8088"
