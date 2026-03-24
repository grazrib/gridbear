"""Skills Service - Manages reusable prompt templates (PostgreSQL)."""

from config.logging_config import logger
from core.interfaces.service import BaseService


class SkillsService(BaseService):
    """Manages reusable skills/prompt templates."""

    name = "skills"

    def __init__(self, config: dict):
        self.config = config
        self._categories = config.get(
            "categories", ["work", "personal", "automation", "report", "other"]
        )

    async def initialize(self) -> None:
        """Initialize service. ORM handles schema/table migration at boot."""
        logger.info("Skills service initialized (ORM)")

    async def shutdown(self) -> None:
        """Shutdown service."""
        logger.info("Skills service shutdown")

    def get_categories(self) -> list[str]:
        """Get available categories."""
        return self._categories

    async def create_skill(
        self,
        name: str,
        title: str,
        prompt: str,
        description: str | None = None,
        category: str = "other",
        created_by: int | None = None,
        created_by_platform: str | None = None,
        shared: bool = True,
    ) -> int:
        """Create a new skill."""
        from plugins.skills.models import Skill

        name = name.lower().replace(" ", "_").replace("-", "_")

        if await Skill.exists(name=name):
            raise ValueError(f"Skill with name '{name}' already exists")

        row = await Skill.create(
            name=name,
            title=title,
            description=description,
            prompt=prompt,
            category=category,
            created_by=created_by,
            created_by_platform=created_by_platform,
            shared=shared,
        )
        skill_id = row["id"]
        logger.info(f"Created skill {skill_id}: {name}")
        return skill_id

    async def get_skill(self, skill_id: int) -> dict | None:
        """Get a skill by ID."""
        from plugins.skills.models import Skill

        results = await Skill.search([("id", "=", skill_id)], limit=1)
        return dict(results[0]) if results else None

    async def get_skill_by_name(self, name: str) -> dict | None:
        """Get a skill by name."""
        from plugins.skills.models import Skill

        name = name.lower().replace(" ", "_").replace("-", "_")
        results = await Skill.search([("name", "=", name)], limit=1)
        return dict(results[0]) if results else None

    async def update_skill(
        self,
        skill_id: int,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        prompt: str | None = None,
        category: str | None = None,
        shared: bool | None = None,
    ) -> bool:
        """Update a skill."""
        from plugins.skills.models import Skill

        updates = {}
        if name is not None:
            updates["name"] = name.lower().replace(" ", "_").replace("-", "_")
        if title is not None:
            updates["title"] = title
        if description is not None:
            updates["description"] = description
        if prompt is not None:
            updates["prompt"] = prompt
        if category is not None:
            updates["category"] = category
        if shared is not None:
            updates["shared"] = shared

        if not updates:
            return False

        # auto_now on updated_at handles the timestamp
        return (await Skill.write(skill_id, **updates)) is not None

    async def delete_skill(self, skill_id: int) -> bool:
        """Delete a skill."""
        from plugins.skills.models import Skill

        deleted = await Skill.delete(skill_id)
        if deleted > 0:
            logger.info(f"Deleted skill {skill_id}")
        return deleted > 0

    async def list_skills(
        self,
        category: str | None = None,
        user_id: int | None = None,
        include_shared: bool = True,
    ) -> list[dict]:
        """List skills with optional filters."""
        from plugins.skills.models import Skill

        domain = []
        if category:
            domain.append(("category", "=", category))

        if user_id is not None and not include_shared:
            domain.append(("created_by", "=", user_id))
        elif user_id is not None and include_shared:
            # OR condition: created_by = user_id OR shared = TRUE
            domain = ["|", ("created_by", "=", user_id), ("shared", "=", True)] + domain

        rows = await Skill.search(domain, order="category, title")
        return [dict(r) for r in rows]

    async def get_all_skills(self) -> list[dict]:
        """Get all skills (for admin)."""
        from plugins.skills.models import Skill

        rows = await Skill.search([], order="category, title")
        return [dict(r) for r in rows]

    async def search_skills(self, query: str) -> list[dict]:
        """Search skills by name, title, or description."""
        from plugins.skills.models import Skill

        pattern = f"%{query}%"
        rows = await Skill.raw_search(
            "SELECT * FROM {table} "
            "WHERE name ILIKE %s OR title ILIKE %s OR description ILIKE %s "
            "ORDER BY title",
            (pattern, pattern, pattern),
        )
        return [dict(r) for r in rows]

    async def seed_skill(
        self,
        name: str,
        title: str,
        prompt: str,
        description: str = "",
        plugin_name: str | None = None,
        category: str = "other",
    ) -> bool:
        """Seed a context skill from a plugin .md file.

        Creates the skill only if it doesn't already exist (by name).
        Returns True if created, False if already present.
        """
        from plugins.skills.models import Skill

        name = name.lower().replace(" ", "_").replace("-", "_")
        if await Skill.exists(name=name):
            return False

        await Skill.create(
            name=name,
            title=title,
            description=description,
            prompt=prompt,
            category=category,
            plugin_name=plugin_name,
            skill_type="context",
            shared=True,
        )
        logger.info(f"Seeded context skill: {name} (plugin: {plugin_name})")
        return True

    async def get_context_skills(
        self, plugin_names: list[str] | None = None
    ) -> list[dict]:
        """Get all context skills, optionally filtered by plugin names."""
        from plugins.skills.models import Skill

        domain = [("skill_type", "=", "context")]
        if plugin_names:
            domain.append(("plugin_name", "in", plugin_names))
        rows = await Skill.search(domain, order="plugin_name, title")
        return [dict(r) for r in rows]

    async def get_user_skills(self, unified_id: str) -> list[dict]:
        """Get user skills visible to a specific user.

        Returns skills created by this user plus shared user skills.
        Looks up the user's DB id from unified_id (username).
        """
        from plugins.skills.models import Skill

        # Resolve unified_id → user DB id
        user_db_id = await self._resolve_user_id(unified_id)
        if user_db_id is None:
            # Unknown user — return only shared user skills
            domain = [
                ("skill_type", "=", "user"),
                ("shared", "=", True),
            ]
        else:
            domain = [
                ("skill_type", "=", "user"),
                "|",
                ("created_by", "=", user_db_id),
                ("shared", "=", True),
            ]
        rows = await Skill.search(domain, order="category, title")
        return [dict(r) for r in rows]

    @staticmethod
    async def _resolve_user_id(unified_id: str) -> int | None:
        """Resolve a unified_id (username) to the app.users primary key."""
        try:
            from core.models.user import User

            user = await User.get(username=unified_id)
            return user["id"] if user else None
        except Exception:
            return None

    async def reset_skill_to_default(self, skill_id: int, default_prompt: str) -> bool:
        """Reset a skill's prompt to the default from the .md file."""
        from plugins.skills.models import Skill

        # auto_now on updated_at handles the timestamp
        return (await Skill.write(skill_id, prompt=default_prompt)) is not None
