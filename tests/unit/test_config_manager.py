"""Tests for ConfigManager (DB-backed)."""

from unittest.mock import MagicMock, patch

import pytest


# ── In-memory ORM mock ──────────────────────────────────────────
class _InMemoryStore:
    """Simulates ORM model *_sync() methods with an in-memory dict."""

    def __init__(self):
        self._rows: dict[int, dict] = {}
        self._seq = 0

    def create_sync(self, **values) -> dict:
        self._seq += 1
        row = {"id": self._seq, **values}
        self._rows[self._seq] = row
        return dict(row)

    def search_sync(self, domain=None, **kwargs) -> list[dict]:
        domain = domain or []
        return [dict(r) for r in self._rows.values() if self._match(r, domain)]

    def get_sync(self, *, raise_if_missing=False, **kwargs) -> dict | None:
        for r in self._rows.values():
            if all(r.get(k) == v for k, v in kwargs.items()):
                return dict(r)
        return None

    def write_sync(self, record_id, **values) -> int:
        if record_id in self._rows:
            self._rows[record_id].update(values)
            return 1
        return 0

    def delete_sync(self, record_id) -> int:
        if record_id in self._rows:
            del self._rows[record_id]
            return 1
        return 0

    def delete_multi_sync(self, domain) -> int:
        to_delete = [rid for rid, r in self._rows.items() if self._match(r, domain)]
        for rid in to_delete:
            del self._rows[rid]
        return len(to_delete)

    def exists_sync(self, domain=None, **kwargs) -> bool:
        if kwargs:
            domain = [(k, "=", v) for k, v in kwargs.items()]
        return bool(self.search_sync(domain))

    def count_sync(self, domain=None, **kwargs) -> int:
        if kwargs:
            domain = [(k, "=", v) for k, v in kwargs.items()]
        return len(self.search_sync(domain))

    def create_or_update_sync(
        self, *, _conflict_fields=None, _update_fields=None, **values
    ) -> dict:
        if _conflict_fields:
            for r in self._rows.values():
                if all(r.get(f) == values.get(f) for f in _conflict_fields):
                    if _update_fields:
                        for uf in _update_fields:
                            if uf in values:
                                r[uf] = values[uf]
                    return dict(r)
        return self.create_sync(**values)

    @staticmethod
    def _match(row: dict, domain: list) -> bool:
        for cond in domain:
            field, op, val = cond
            rv = row.get(field)
            if op == "=" and rv != val:
                return False
            elif op == "!=" and rv == val:
                return False
            elif op == "in" and rv not in val:
                return False
        return True


# ── Fixtures ────────────────────────────────────────────────────


def _make_model_mock(store: _InMemoryStore) -> MagicMock:
    """Build a MagicMock whose *_sync methods delegate to store."""
    m = MagicMock()
    m.create_sync = store.create_sync
    m.search_sync = store.search_sync
    m.get_sync = store.get_sync
    m.write_sync = store.write_sync
    m.delete_sync = store.delete_sync
    m.delete_multi_sync = store.delete_multi_sync
    m.exists_sync = store.exists_sync
    m.count_sync = store.count_sync
    m.create_or_update_sync = store.create_or_update_sync
    return m


@pytest.fixture(autouse=True)
def mock_orm_models():
    """Patch all ORM models used by ConfigManager with in-memory stores."""
    stores = {
        "ChannelAuthorizedUser": _InMemoryStore(),
        "UserPlatform": _InMemoryStore(),
        "User": _InMemoryStore(),
        "UserMcpPermission": _InMemoryStore(),
        "MemoryGroup": _InMemoryStore(),
        "GroupMcpPermission": _InMemoryStore(),
        "UserServiceAccount": _InMemoryStore(),
        "OAuthToken": _InMemoryStore(),
    }
    mocks = {name: _make_model_mock(store) for name, store in stores.items()}

    # SystemConfig needs get_param_sync / set_param_sync
    sys_config_store = _InMemoryStore()
    sys_config = MagicMock()
    sys_config.get_sync = sys_config_store.get_sync
    sys_config.delete_sync = sys_config_store.delete_sync
    _sys_params: dict[str, object] = {}

    def get_param_sync(key, default=None):
        return _sys_params.get(key, default)

    def set_param_sync(key, value):
        _sys_params[key] = value

    sys_config.get_param_sync = get_param_sync
    sys_config.set_param_sync = set_param_sync

    with (
        patch(
            "ui.config_manager.ChannelAuthorizedUser", mocks["ChannelAuthorizedUser"]
        ),
        patch("ui.config_manager.UserPlatform", mocks["UserPlatform"]),
        patch("ui.config_manager.User", mocks["User"]),
        patch("ui.config_manager.UserMcpPermission", mocks["UserMcpPermission"]),
        patch("ui.config_manager.MemoryGroup", mocks["MemoryGroup"]),
        patch("ui.config_manager.GroupMcpPermission", mocks["GroupMcpPermission"]),
        patch("ui.config_manager.UserServiceAccount", mocks["UserServiceAccount"]),
        patch("ui.config_manager.OAuthToken", mocks["OAuthToken"]),
        patch("ui.config_manager.SystemConfig", sys_config),
    ):
        yield {"stores": stores, "mocks": mocks, "sys_config": sys_config}


def _create_user(mock_data, username, locale="en"):
    """Helper: create a User in the mock store."""
    return mock_data["stores"]["User"].create_sync(username=username, locale=locale)


class TestConfigManagerInit:
    """Tests for ConfigManager initialization."""

    def test_init_no_error(self):
        """Should initialize without error."""
        from ui.config_manager import ConfigManager

        ConfigManager()


class TestChannelUsers:
    """Tests for generic channel user management."""

    def test_add_channel_user_by_id(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_channel_user("telegram", user_id=999)

        users = config.get_channel_users("telegram")
        assert 999 in users["ids"]

    def test_add_channel_user_by_username(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_channel_user("telegram", username="@TestUser")

        users = config.get_channel_users("telegram")
        assert "testuser" in users["usernames"]

    def test_add_duplicate_user_ignored(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_channel_user("telegram", user_id=123)
        config.add_channel_user("telegram", user_id=123)

        users = config.get_channel_users("telegram")
        assert users["ids"].count(123) == 1

    def test_remove_channel_user_by_id(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_channel_user("telegram", user_id=123)
        config.remove_channel_user("telegram", user_id=123)

        users = config.get_channel_users("telegram")
        assert 123 not in users["ids"]

    def test_remove_channel_user_by_username(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_channel_user("telegram", username="testuser")
        config.remove_channel_user("telegram", username="@TestUser")

        users = config.get_channel_users("telegram")
        assert "testuser" not in users["usernames"]

    def test_discord_add_user(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_channel_user("discord", user_id=456, username="discorduser")

        users = config.get_channel_users("discord")
        assert 456 in users["ids"]
        assert "discorduser" in users["usernames"]

    def test_discord_remove_user(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_channel_user("discord", username="toremove")
        config.remove_channel_user("discord", username="toremove")

        users = config.get_channel_users("discord")
        assert "toremove" not in users["usernames"]


class TestUserIdentities:
    """Tests for cross-platform user identities (UserPlatform-based)."""

    def test_add_user_identity(self, mock_orm_models):
        from ui.config_manager import ConfigManager

        _create_user(mock_orm_models, "mario")
        config = ConfigManager()
        config.add_user_identity("mario", "telegram", "@MarioRossi")

        identities = config.get_user_identities()
        assert "mario" in identities
        assert identities["mario"]["telegram"] == "mariorossi"

    def test_get_unified_user_id(self, mock_orm_models):
        from ui.config_manager import ConfigManager

        _create_user(mock_orm_models, "luigi")
        config = ConfigManager()
        config.add_user_identity("luigi", "discord", "luigi123")

        unified_id = config.get_unified_user_id("discord", "luigi123")
        assert unified_id == "luigi"

    def test_get_unified_user_id_not_found(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        unified_id = config.get_unified_user_id("telegram", "nonexistent")
        assert unified_id is None

    def test_remove_user_identity_platform(self, mock_orm_models):
        from ui.config_manager import ConfigManager

        _create_user(mock_orm_models, "test")
        config = ConfigManager()
        config.add_user_identity("test", "telegram", "tguser")
        config.add_user_identity("test", "discord", "dcuser")
        config.remove_user_identity("test", "telegram")

        identities = config.get_user_identities()
        assert "telegram" not in identities["test"]
        assert "discord" in identities["test"]

    def test_remove_user_identity_completely(self, mock_orm_models):
        from ui.config_manager import ConfigManager

        _create_user(mock_orm_models, "test")
        config = ConfigManager()
        config.add_user_identity("test", "telegram", "tguser")
        config.remove_user_identity("test")

        identities = config.get_user_identities()
        assert "test" not in identities

    def test_get_channel_username(self, mock_orm_models):
        from ui.config_manager import ConfigManager

        _create_user(mock_orm_models, "mario")
        config = ConfigManager()
        config.add_user_identity("mario", "telegram", "mariorossi")

        uname = config.get_channel_username("mario", "telegram")
        assert uname == "mariorossi"

    def test_get_channel_username_not_found(self, mock_orm_models):
        from ui.config_manager import ConfigManager

        _create_user(mock_orm_models, "mario")
        config = ConfigManager()

        uname = config.get_channel_username("mario", "discord")
        assert uname is None

    def test_add_identity_nonexistent_user(self, mock_orm_models):
        """Adding identity for non-existent user is a no-op."""
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_user_identity("ghost", "telegram", "ghostuser")

        identities = config.get_user_identities()
        assert "ghost" not in identities


class TestUserPermissions:
    """Tests for MCP permissions."""

    def test_set_user_permissions(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.set_user_permissions("testuser", ["odoo", "gmail", "homeassistant"])

        perms = config.get_user_permissions("testuser")
        assert sorted(perms) == ["gmail", "homeassistant", "odoo"]

    def test_get_user_permissions_not_set(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        perms = config.get_user_permissions("unknownuser")
        assert perms is None

    def test_delete_user_permissions(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.set_user_permissions("testuser", ["odoo"])
        config.delete_user_permissions("testuser")

        perms = config.get_user_permissions("testuser")
        assert perms is None


class TestMemoryGroups:
    """Tests for memory group management."""

    def test_add_memory_group(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_memory_group("family", ["mario", "luigi"])

        groups = config.get_memory_groups()
        assert "family" in groups
        assert "mario" in groups["family"]
        assert "luigi" in groups["family"]

    def test_add_user_to_memory_group(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_memory_group("team", ["user1"])
        config.add_user_to_memory_group("team", "user2")

        members = config.get_memory_group_members("team")
        assert "user1" in members
        assert "user2" in members

    def test_get_user_memory_group(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_memory_group("developers", ["dev1", "dev2"])

        group = config.get_user_memory_group("dev1")
        assert group == "developers"

    def test_remove_user_from_memory_group(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_memory_group("team", ["user1", "user2"])
        config.remove_user_from_memory_group("team", "user1")

        members = config.get_memory_group_members("team")
        assert "user1" not in members
        assert "user2" in members

    def test_empty_group_after_remove(self):
        """Group rows are deleted when all members removed."""
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_memory_group("solo", ["onlyone"])
        config.remove_user_from_memory_group("solo", "onlyone")

        groups = config.get_memory_groups()
        assert "solo" not in groups


class TestUserLocales:
    """Tests for user locale preferences (stored on User.locale)."""

    def test_set_user_locale(self, mock_orm_models):
        from ui.config_manager import ConfigManager

        _create_user(mock_orm_models, "testuser")
        config = ConfigManager()
        config.set_user_locale("testuser", "IT")

        locale = config.get_user_locale("testuser")
        assert locale == "it"

    def test_get_user_locale_default(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        locale = config.get_user_locale("unknownuser")
        assert locale == "en"

    def test_delete_user_locale(self, mock_orm_models):
        from ui.config_manager import ConfigManager

        _create_user(mock_orm_models, "testuser", locale="it")
        config = ConfigManager()
        config.delete_user_locale("testuser")

        locale = config.get_user_locale("testuser")
        assert locale == "en"

    def test_get_user_locales_all(self, mock_orm_models):
        from ui.config_manager import ConfigManager

        _create_user(mock_orm_models, "mario", locale="it")
        _create_user(mock_orm_models, "luigi", locale="de")
        config = ConfigManager()

        locales = config.get_user_locales()
        assert locales["mario"] == "it"
        assert locales["luigi"] == "de"


class TestGmailAccounts:
    """Tests for Gmail account management."""

    def test_add_gmail_account(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_gmail_account("testuser", "test@gmail.com")

        accounts = config.get_gmail_accounts()
        assert "testuser" in accounts
        assert "test@gmail.com" in accounts["testuser"]

    def test_add_multiple_gmail_accounts(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_gmail_account("testuser", "personal@gmail.com")
        config.add_gmail_account("testuser", "work@gmail.com")

        accounts = config.get_gmail_accounts()
        assert len(accounts["testuser"]) == 2

    def test_remove_gmail_account(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.add_gmail_account("testuser", "tokeep@gmail.com")
        config.add_gmail_account("testuser", "toremove@gmail.com")
        config.remove_gmail_account("testuser", "toremove@gmail.com")

        accounts = config.get_gmail_accounts()
        assert "tokeep@gmail.com" in accounts["testuser"]
        assert "toremove@gmail.com" not in accounts["testuser"]


class TestBotSettings:
    """Tests for bot identity and email settings."""

    def test_set_bot_identity(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.set_bot_identity("gridbear")

        identity = config.get_bot_identity()
        assert identity == "gridbear"

    def test_clear_bot_identity(self, mock_orm_models):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        config.set_bot_identity("gridbear")
        config.set_bot_identity(None)

        identity = config.get_bot_identity()
        assert identity is None

    def test_get_bot_email_settings_default(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        settings = config.get_bot_email_settings()

        assert settings["enabled"] is False
        assert settings["check_interval_minutes"] == 5
        assert settings["label"] == "INBOX"

    def test_set_bot_email_settings(self):
        from ui.config_manager import ConfigManager

        config = ConfigManager()
        new_settings = {
            "enabled": True,
            "check_interval_minutes": 10,
            "label": "GRIDBEAR",
            "instructions": "Handle support emails",
        }
        config.set_bot_email_settings(new_settings)

        settings = config.get_bot_email_settings()
        assert settings["enabled"] is True
        assert settings["check_interval_minutes"] == 10
