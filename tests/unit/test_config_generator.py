"""Tests for plugins.claude.config_generator."""

import json

import pytest


@pytest.fixture
def gen_module(tmp_path, monkeypatch):
    """Import config_generator with patched paths."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    monkeypatch.setattr("plugins.claude.config_generator.CLAUDE_HOME", claude_home)
    monkeypatch.setattr(
        "plugins.claude.config_generator.SETTINGS_PATH",
        claude_home / "settings.local.json",
    )
    monkeypatch.setattr(
        "plugins.claude.config_generator.CLAUDE_JSON_PATH",
        tmp_path / ".claude.json",
    )
    monkeypatch.setattr(
        "plugins.claude.config_generator.CONTAINER_JSON",
        tmp_path / ".claude.container.json",
    )

    from plugins.claude import config_generator

    return config_generator, tmp_path, claude_home


class TestGenerateSettingsLocal:
    def test_generates_from_source(self, gen_module, monkeypatch):
        mod, tmp_path, claude_home = gen_module
        source = {"permissions": {"allow": ["Bash", "Read"]}}
        monkeypatch.setattr(
            "core.system_config.SystemConfig.get_param_sync",
            staticmethod(
                lambda key, default=None: (
                    source if key == "claude_settings" else default
                )
            ),
        )

        assert mod.generate_settings_local() is True

        result = json.loads((claude_home / "settings.local.json").read_text())
        assert result == source

    def test_skips_when_no_source(self, gen_module, monkeypatch):
        mod, _, _ = gen_module
        monkeypatch.setattr(
            "core.system_config.SystemConfig.get_param_sync",
            staticmethod(lambda key, default=None: default),
        )
        assert mod.generate_settings_local() is False

    def test_skips_when_unchanged(self, gen_module, monkeypatch):
        mod, tmp_path, claude_home = gen_module
        source = {"permissions": {"allow": ["Bash"]}}
        monkeypatch.setattr(
            "core.system_config.SystemConfig.get_param_sync",
            staticmethod(
                lambda key, default=None: (
                    source if key == "claude_settings" else default
                )
            ),
        )
        (claude_home / "settings.local.json").write_text(json.dumps(source))

        mtime_before = (claude_home / "settings.local.json").stat().st_mtime
        assert mod.generate_settings_local() is True
        mtime_after = (claude_home / "settings.local.json").stat().st_mtime
        assert mtime_before == mtime_after  # not rewritten

    def test_overwrites_when_changed(self, gen_module, monkeypatch):
        mod, tmp_path, claude_home = gen_module
        source = {"permissions": {"allow": ["Bash", "Read"]}}
        monkeypatch.setattr(
            "core.system_config.SystemConfig.get_param_sync",
            staticmethod(
                lambda key, default=None: (
                    source if key == "claude_settings" else default
                )
            ),
        )
        (claude_home / "settings.local.json").write_text(
            json.dumps({"permissions": {"allow": ["Bash"]}})
        )

        assert mod.generate_settings_local() is True
        result = json.loads((claude_home / "settings.local.json").read_text())
        assert "Read" in result["permissions"]["allow"]


class TestGenerateClaudeJson:
    def test_uses_container_json_projects(self, gen_module):
        mod, tmp_path, _ = gen_module
        container_data = {
            "projects": {
                "/app": {
                    "allowedTools": ["mcp__odoo-mcp__search", "Bash"],
                    "mcpServers": {"odoo-mcp": {"type": "sse", "url": "http://x"}},
                    "hasTrustDialogAccepted": True,
                },
                "/projects/myproject": {
                    "allowedTools": ["Bash", "Read"],
                    "hasTrustDialogAccepted": True,
                },
            },
            "userID": "abc123",
            "oauthAccount": {"email": "test@test.com"},
        }
        (tmp_path / ".claude.container.json").write_text(json.dumps(container_data))

        assert mod.generate_claude_json() is True

        result = json.loads((tmp_path / ".claude.json").read_text())
        # Projects section populated from container json
        assert "/app" in result["projects"]
        assert "/projects/myproject" in result["projects"]
        assert "mcp__odoo-mcp__search" in result["projects"]["/app"]["allowedTools"]
        # Auth fields NOT copied from container json (that's a different file)
        assert "oauthAccount" not in result

    def test_preserves_existing_auth(self, gen_module):
        mod, tmp_path, _ = gen_module
        # Simulate existing .claude.json with auth data from login
        existing = {
            "oauthAccount": {"email": "user@example.com", "accountUuid": "xxx"},
            "userID": "existing-id",
            "projects": {"/old": {"allowedTools": []}},
        }
        (tmp_path / ".claude.json").write_text(json.dumps(existing))

        # Container json has new project config
        (tmp_path / ".claude.container.json").write_text(
            json.dumps({"projects": {"/app": {"allowedTools": ["Bash"]}}})
        )

        mod.generate_claude_json()

        result = json.loads((tmp_path / ".claude.json").read_text())
        # Auth preserved
        assert result["oauthAccount"]["email"] == "user@example.com"
        assert result["userID"] == "existing-id"
        # Projects updated (old project replaced)
        assert "/app" in result["projects"]
        assert "/old" not in result["projects"]

    def test_defaults_when_no_container_json(self, gen_module):
        mod, tmp_path, _ = gen_module
        # No .claude.container.json

        mod.generate_claude_json()

        result = json.loads((tmp_path / ".claude.json").read_text())
        assert "/app" in result["projects"]
        assert "hasTrustDialogAccepted" in result["projects"]["/app"]

    def test_explicit_project_config_overrides(self, gen_module):
        mod, tmp_path, _ = gen_module
        (tmp_path / ".claude.container.json").write_text(
            json.dumps({"projects": {"/app": {"allowedTools": ["old"]}}})
        )

        custom = {"/custom": {"allowedTools": ["Write"]}}
        mod.generate_claude_json(project_config=custom)

        result = json.loads((tmp_path / ".claude.json").read_text())
        assert "/custom" in result["projects"]
        assert "/app" not in result["projects"]

    def test_skips_write_when_unchanged(self, gen_module):
        mod, tmp_path, _ = gen_module
        projects = {"/app": {"allowedTools": ["Bash"]}}
        (tmp_path / ".claude.container.json").write_text(
            json.dumps({"projects": projects})
        )

        mod.generate_claude_json()
        mtime1 = (tmp_path / ".claude.json").stat().st_mtime

        mod.generate_claude_json()
        mtime2 = (tmp_path / ".claude.json").stat().st_mtime
        assert mtime1 == mtime2  # not rewritten


class TestGenerateAll:
    def test_runs_both_steps(self, gen_module, monkeypatch):
        mod, tmp_path, claude_home = gen_module
        source = {"permissions": {"allow": ["Bash"]}}
        monkeypatch.setattr(
            "core.system_config.SystemConfig.get_param_sync",
            staticmethod(
                lambda key, default=None: (
                    source if key == "claude_settings" else default
                )
            ),
        )
        (tmp_path / ".claude.container.json").write_text(
            json.dumps({"projects": {"/app": {"allowedTools": ["Read"]}}})
        )

        mod.generate_all()

        assert (claude_home / "settings.local.json").exists()
        assert (tmp_path / ".claude.json").exists()

        settings = json.loads((claude_home / "settings.local.json").read_text())
        assert settings["permissions"]["allow"] == ["Bash"]

        claude_json = json.loads((tmp_path / ".claude.json").read_text())
        assert "Read" in claude_json["projects"]["/app"]["allowedTools"]
