"""One-time migration: admin_config.json -> PostgreSQL ORM models.

Follows the same idempotent pattern as the plugins.json migration in
``core/plugin_registry/registry.py``:
  1. Check SystemConfig marker — if set, skip
  2. Read JSON file
  3. INSERT into ORM models
  4. Set marker
  5. Rename file to ``.migrated``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MARKER_KEY = "_migration_admin_config"
_MARKER_REST_API_KEY = "_migration_rest_api_config"
_MARKER_CLAUDE_SETTINGS_KEY = "_migration_claude_settings"
_MARKER_MCP_PERMS_UNIFIED_ID = "_migration_mcp_perms_unified_id"
_MARKER_DEFAULT_COMPANY = "_migration_default_company"


async def migrate_admin_config_to_db(config_path: Path) -> bool:
    """Migrate admin_config.json data into PostgreSQL tables.

    Returns True if migration was performed, False if skipped.
    """
    from core.config_models import (
        ChannelAuthorizedUser,
        GroupMcpPermission,
        MemoryGroup,
        OAuthToken,
        UserIdentity,
        UserMcpPermission,
        UserProfile,
        UserServiceAccount,
    )
    from core.system_config import SystemConfig

    # 1. Check marker
    marker = await SystemConfig.get_param(_MARKER_KEY)
    if marker:
        return False

    # 2. Read file
    if not config_path.exists():
        logger.info("No admin_config.json found — marking migration as done")
        await SystemConfig.set_param(_MARKER_KEY, True)
        return False

    try:
        with open(config_path) as f:
            config = json.load(f)
    except (json.JSONDecodeError, IOError) as exc:
        logger.error("Failed to read admin_config.json: %s", exc)
        return False

    logger.info("Migrating admin_config.json to PostgreSQL...")

    # 3. Migrate each section

    # --- Channel authorized users ---
    for key, data in config.items():
        if not key.endswith("_authorized"):
            continue
        channel = key.removesuffix("_authorized")
        for uid in data.get("ids", []):
            try:
                await ChannelAuthorizedUser.create(
                    channel=channel, platform_user_id=uid
                )
            except Exception as exc:
                logger.debug("Channel user %s/%s skip: %s", channel, uid, exc)
        for uname in data.get("usernames", []):
            try:
                await ChannelAuthorizedUser.create(
                    channel=channel, username=uname.lower()
                )
            except Exception as exc:
                logger.debug("Channel user %s/%s skip: %s", channel, uname, exc)

    # --- User identities ---
    for unified_id, platforms in config.get("user_identities", {}).items():
        unified_id = unified_id.lower()
        for platform, username in platforms.items():
            try:
                await UserIdentity.create(
                    unified_id=unified_id,
                    platform=platform.lower(),
                    username=username.lower().lstrip("@"),
                )
            except Exception as exc:
                logger.debug("Identity %s/%s skip: %s", unified_id, platform, exc)

    # --- User MCP permissions (stored by unified_id) ---
    # Legacy JSON used usernames; resolve to unified_id via identity mapping
    identity_map = {}
    for uid, platforms in config.get("user_identities", {}).items():
        for _platform, uname in platforms.items():
            identity_map[uname.lower().lstrip("@")] = uid.lower()

    for username, servers in config.get("user_permissions", {}).items():
        username_lower = username.lower().lstrip("@")
        uid = identity_map.get(username_lower, username_lower)
        for server in servers:
            try:
                await UserMcpPermission.create(unified_id=uid, server_name=server)
            except Exception as exc:
                logger.debug("MCP perm %s/%s skip: %s", uid, server, exc)

    # --- Memory groups ---
    for group_name, members in config.get("memory_groups", {}).items():
        group_name = group_name.lower()
        for member in members:
            try:
                await MemoryGroup.create(
                    group_name=group_name, unified_id=member.lower()
                )
            except Exception as exc:
                logger.debug("Memory group %s/%s skip: %s", group_name, member, exc)

    # --- Group permissions ---
    for group_name, servers in config.get("group_permissions", {}).items():
        group_name = group_name.lower()
        for server in servers:
            try:
                await GroupMcpPermission.create(
                    group_name=group_name, server_name=server
                )
            except Exception as exc:
                logger.debug("Group perm %s/%s skip: %s", group_name, server, exc)

    # --- Gmail accounts -> UserServiceAccount ---
    for unified_id, emails in config.get("gmail_accounts", {}).items():
        unified_id = unified_id.lower()
        if isinstance(emails, str):
            emails = [emails]
        for email in emails:
            try:
                await UserServiceAccount.create(
                    unified_id=unified_id,
                    service_type="gmail",
                    account_id=email,
                )
            except Exception as exc:
                logger.debug("Service acct %s/%s skip: %s", unified_id, email, exc)

    # --- User locales -> UserProfile ---
    for unified_id, locale in config.get("user_locales", {}).items():
        try:
            await UserProfile.create(
                unified_id=unified_id.lower(), locale=locale.lower()
            )
        except Exception as exc:
            logger.debug("User profile %s skip: %s", unified_id, exc)

    # --- OAuth tokens (ephemeral, but migrate any still valid) ---
    for token, data in config.get("oauth_tokens", {}).items():
        try:
            await OAuthToken.create(
                token=token, unified_id=data.get("unified_id", "").lower()
            )
        except Exception as exc:
            logger.debug("OAuth token skip: %s", exc)

    # --- Global settings -> SystemConfig ---
    bot_identity = config.get("bot_identity")
    if bot_identity:
        await SystemConfig.set_param("bot_identity", bot_identity)

    bot_email = config.get("bot_email_settings")
    if bot_email:
        await SystemConfig.set_param("bot_email_settings", bot_email)

    tts = config.get("webchat_tts_provider")
    if tts:
        await SystemConfig.set_param("webchat_tts_provider", tts)

    # 4. Mark migration as done
    await SystemConfig.set_param(_MARKER_KEY, True)

    # 5. Rename file
    migrated_path = config_path.with_suffix(".json.migrated")
    try:
        config_path.rename(migrated_path)
        logger.info("Renamed admin_config.json -> admin_config.json.migrated")
    except OSError as exc:
        logger.warning("Could not rename admin_config.json: %s", exc)

    logger.info("Migrated admin_config.json to PostgreSQL successfully")
    return True


async def migrate_rest_api_config_to_db(config_path: Path) -> bool:
    """Migrate rest_api.json data into PostgreSQL SystemConfig.

    Returns True if migration was performed, False if skipped.
    """
    from core.system_config import SystemConfig

    # 1. Check marker
    marker = await SystemConfig.get_param(_MARKER_REST_API_KEY)
    if marker:
        return False

    # 2. Read file
    if not config_path.exists():
        logger.info("No rest_api.json found — marking migration as done")
        await SystemConfig.set_param(_MARKER_REST_API_KEY, True)
        return False

    try:
        with open(config_path) as f:
            config = json.load(f)
    except (json.JSONDecodeError, IOError) as exc:
        logger.error("Failed to read rest_api.json: %s", exc)
        return False

    logger.info("Migrating rest_api.json to PostgreSQL...")

    # 3. Store as single SystemConfig parameter
    await SystemConfig.set_param("rest_api_config", config)

    # 4. Mark migration as done
    await SystemConfig.set_param(_MARKER_REST_API_KEY, True)

    # 5. Rename file
    migrated_path = config_path.with_suffix(".json.migrated")
    try:
        config_path.rename(migrated_path)
        logger.info("Renamed rest_api.json -> rest_api.json.migrated")
    except OSError as exc:
        logger.warning("Could not rename rest_api.json: %s", exc)

    logger.info("Migrated rest_api.json to PostgreSQL successfully")
    return True


async def migrate_claude_settings_to_db(config_path: Path) -> bool:
    """Migrate claude_settings.json data into PostgreSQL SystemConfig.

    Returns True if migration was performed, False if skipped.
    """
    from core.system_config import SystemConfig

    # 1. Check marker
    marker = await SystemConfig.get_param(_MARKER_CLAUDE_SETTINGS_KEY)
    if marker:
        return False

    # 2. Read file
    if not config_path.exists():
        logger.info("No claude_settings.json found — marking migration as done")
        await SystemConfig.set_param(_MARKER_CLAUDE_SETTINGS_KEY, True)
        return False

    try:
        with open(config_path) as f:
            config = json.load(f)
    except (json.JSONDecodeError, IOError) as exc:
        logger.error("Failed to read claude_settings.json: %s", exc)
        return False

    logger.info("Migrating claude_settings.json to PostgreSQL...")

    # 3. Store as single SystemConfig parameter
    await SystemConfig.set_param("claude_settings", config)

    # 4. Mark migration as done
    await SystemConfig.set_param(_MARKER_CLAUDE_SETTINGS_KEY, True)

    # 5. Rename file
    migrated_path = config_path.with_suffix(".json.migrated")
    try:
        config_path.rename(migrated_path)
        logger.info("Renamed claude_settings.json -> claude_settings.json.migrated")
    except OSError as exc:
        logger.warning("Could not rename claude_settings.json: %s", exc)

    logger.info("Migrated claude_settings.json to PostgreSQL successfully")
    return True


async def migrate_mcp_perms_to_unified_id() -> bool:
    """Backfill user_mcp_permissions.unified_id from old username column.

    For existing rows where unified_id is NULL but username is populated,
    resolves the unified_id via user_identities mapping (or falls back to
    using the username value as-is).

    Returns True if migration was performed, False if skipped.
    """
    from core.registry import get_database
    from core.system_config import SystemConfig

    marker = await SystemConfig.get_param(_MARKER_MCP_PERMS_UNIFIED_ID)
    if marker:
        return False

    db = get_database()
    async with db.acquire() as conn:
        # Check if the old username column still exists
        col_check = await conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'app' AND table_name = 'user_mcp_permissions' "
            "AND column_name = 'username'"
        )
        if not await col_check.fetchone():
            # No old column — nothing to migrate
            await SystemConfig.set_param(_MARKER_MCP_PERMS_UNIFIED_ID, True)
            return False

        # Backfill: resolve username -> unified_id via user_identities
        # Step 1: resolve all target unified_ids and deduplicate.
        # Multiple platform usernames may map to the same unified_id,
        # so we keep only the first row per (target_uid, server_name).
        await conn.execute(
            """
            WITH resolved AS (
                SELECT p.id,
                       COALESCE(
                           (SELECT ui.unified_id FROM app.user_identities ui
                            WHERE LOWER(ui.username) = LOWER(p.username) LIMIT 1),
                           p.username
                       ) AS target_uid,
                       p.server_name,
                       ROW_NUMBER() OVER (
                           PARTITION BY
                               COALESCE(
                                   (SELECT ui.unified_id FROM app.user_identities ui
                                    WHERE LOWER(ui.username) = LOWER(p.username) LIMIT 1),
                                   p.username
                               ),
                               p.server_name
                           ORDER BY p.id
                       ) AS rn
                FROM app.user_mcp_permissions p
                WHERE p.unified_id IS NULL AND p.username IS NOT NULL
            )
            DELETE FROM app.user_mcp_permissions
            WHERE id IN (SELECT r.id FROM resolved r WHERE r.rn > 1)
            """
        )

        # Step 2: also delete rows that conflict with already-migrated rows
        await conn.execute(
            """
            WITH resolved AS (
                SELECT p.id,
                       COALESCE(
                           (SELECT ui.unified_id FROM app.user_identities ui
                            WHERE LOWER(ui.username) = LOWER(p.username) LIMIT 1),
                           p.username
                       ) AS target_uid,
                       p.server_name
                FROM app.user_mcp_permissions p
                WHERE p.unified_id IS NULL AND p.username IS NOT NULL
            )
            DELETE FROM app.user_mcp_permissions
            WHERE id IN (
                SELECT r.id FROM resolved r
                WHERE EXISTS (
                    SELECT 1 FROM app.user_mcp_permissions existing
                    WHERE existing.unified_id = r.target_uid
                    AND existing.server_name = r.server_name
                    AND existing.id != r.id
                )
            )
            """
        )

        # Step 3: update remaining rows
        result = await conn.execute(
            """
            UPDATE app.user_mcp_permissions p
            SET unified_id = COALESCE(
                (SELECT ui.unified_id FROM app.user_identities ui
                 WHERE LOWER(ui.username) = LOWER(p.username)
                 LIMIT 1),
                p.username
            )
            WHERE p.unified_id IS NULL AND p.username IS NOT NULL
            """
        )
        count = result.rowcount if hasattr(result, "rowcount") else 0
        if count:
            logger.info(
                "Migrated %d MCP permission rows: username -> unified_id", count
            )

    await SystemConfig.set_param(_MARKER_MCP_PERMS_UNIFIED_ID, True)
    logger.info("MCP permissions unified_id migration complete")
    return True


async def migrate_create_default_company() -> bool:
    """Create the default company and assign all existing users to it.

    Steps:
      1. Create default company (id=1, slug="default")
      2. Insert CompanyUser for each existing app.users row

    Returns True if migration was performed, False if skipped.
    """
    from core.registry import get_database
    from core.system_config import SystemConfig

    marker = await SystemConfig.get_param(_MARKER_DEFAULT_COMPANY)
    if marker:
        return False

    db = get_database()
    async with db.acquire() as conn:
        # Check if companies table exists (ORM should have created it)
        tbl_check = await conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'app' AND table_name = 'companies'"
        )
        if not await tbl_check.fetchone():
            logger.warning("app.companies table not found — skipping company migration")
            await SystemConfig.set_param(_MARKER_DEFAULT_COMPANY, True)
            return False

        # 1. Create default company with OVERRIDING SYSTEM VALUE to force id=1
        await conn.execute(
            """
            INSERT INTO app.companies (id, name, slug, active, locale, timezone, plan)
            OVERRIDING SYSTEM VALUE
            VALUES (1, 'Default', 'default', TRUE, 'en', 'UTC', 'free')
            ON CONFLICT (id) DO NOTHING
            """
        )

        # Reset the sequence to avoid id collision on next insert
        await conn.execute(
            "SELECT setval(pg_get_serial_sequence('app.companies', 'id'), "
            "GREATEST((SELECT MAX(id) FROM app.companies), 1))"
        )

        # 2. Insert CompanyUser for each existing user
        result = await conn.execute(
            """
            INSERT INTO app.company_users (company_id, user_id, role, is_default)
            SELECT 1, u.id,
                   CASE WHEN u.is_superadmin THEN 'owner' ELSE 'admin' END,
                   TRUE
            FROM app.users u
            WHERE NOT EXISTS (
                SELECT 1 FROM app.company_users cu
                WHERE cu.company_id = 1 AND cu.user_id = u.id
            )
            """
        )
        count = result.rowcount if hasattr(result, "rowcount") else 0
        if count:
            logger.info("Assigned %d users to default company", count)

    await SystemConfig.set_param(_MARKER_DEFAULT_COMPANY, True)
    logger.info("Default company migration complete")
    return True
