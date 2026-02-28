"""Memo Service - Scheduled tasks and reminders with separate prompt storage (PostgreSQL)."""

from datetime import datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from config.logging_config import logger
from core.interfaces.service import BaseSchedulerService


class MemoService(BaseSchedulerService):
    """Manages scheduled memos/reminders with separate prompt storage."""

    name = "memo"

    def __init__(self, config: dict):
        self.config = config
        self._timezone = ZoneInfo(config.get("timezone", "Europe/Rome"))
        self._max_memos = config.get("max_memos_per_user", 50)
        self._max_prompts = config.get("max_prompts_per_user", 100)
        self.scheduler = AsyncIOScheduler(timezone=self._timezone)
        self._callback: Callable[[int, int, str, str], Awaitable[None]] | None = None

    async def initialize(self) -> None:
        """Initialize scheduler and load persisted memos. ORM handles migration."""
        await self._load_memos()
        self.scheduler.start()
        logger.info(f"Memo service initialized (timezone: {self._timezone})")

    async def shutdown(self) -> None:
        """Shutdown scheduler gracefully."""
        self.scheduler.shutdown(wait=True)
        logger.info("Memo service shutdown")

    def set_callback(
        self, callback: Callable[[int, int, str, str], Awaitable[None]]
    ) -> None:
        """Set callback for memo execution: callback(memo_id, user_id, platform, prompt_content)."""
        self._callback = callback

    async def _load_memos(self) -> None:
        """Load persisted memos and schedule them."""
        from plugins.memo.models import ScheduledMemo

        rows = await ScheduledMemo.raw_search(
            "SELECT m.*, p.content as prompt_content, p.title as prompt_title "
            "FROM {table} m "
            "JOIN app.memo_prompts p ON m.prompt_id = p.id "
            "WHERE m.enabled = TRUE",
        )
        for memo in rows:
            self._add_job(dict(memo))
        logger.info(f"Loaded {len(rows)} scheduled memos")

    def _add_job(self, memo: dict) -> None:
        """Add a job to the scheduler."""
        job_id = f"memo_{memo['id']}"

        if memo["schedule_type"] == "cron" and memo.get("cron"):
            parts = memo["cron"].split()
            if len(parts) >= 5:
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    timezone=self._timezone,
                )
            else:
                logger.warning(
                    f"Invalid cron expression for memo {job_id}: {memo['cron']}"
                )
                return
        elif memo["schedule_type"] == "once" and memo.get("run_at"):
            run_at = datetime.fromisoformat(memo["run_at"])
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=self._timezone)
            if run_at <= datetime.now(self._timezone):
                logger.debug(f"Skipping past memo {job_id}")
                return
            trigger = DateTrigger(run_date=run_at, timezone=self._timezone)
        else:
            logger.warning(f"Invalid memo configuration: {memo}")
            return

        self.scheduler.add_job(
            self._execute_memo,
            trigger=trigger,
            id=job_id,
            args=[
                memo["id"],
                memo["user_id"],
                memo["platform"],
                memo["prompt_content"],
            ],
            replace_existing=True,
        )
        logger.debug(f"Scheduled memo {job_id}: {memo.get('prompt_title', 'untitled')}")

    async def _execute_memo(
        self, memo_id: int, user_id: int, platform: str, prompt_content: str
    ) -> None:
        """Execute a scheduled memo."""
        from plugins.memo.models import ScheduledMemo

        logger.info(f"Executing memo {memo_id} for user {user_id}")

        # Update last_run
        await ScheduledMemo.write(memo_id, last_run=datetime.now(self._timezone))

        # Call the callback
        if self._callback:
            try:
                await self._callback(memo_id, user_id, platform, prompt_content)
            except Exception as e:
                logger.error(f"Error executing memo {memo_id}: {e}")

        # Check if one-time memo, disable it
        rows = await ScheduledMemo.search([("id", "=", memo_id)], limit=1)
        if rows and rows[0]["schedule_type"] == "once":
            await ScheduledMemo.write(memo_id, enabled=False)

    # ========== PROMPT METHODS ==========

    async def create_prompt(
        self,
        user_id: int,
        platform: str,
        title: str,
        content: str,
    ) -> int:
        """Create a new reusable prompt."""
        from plugins.memo.models import MemoPrompt

        if self._max_prompts > 0:
            count = await self.count_prompts(user_id, platform)
            if count >= self._max_prompts:
                raise ValueError(f"Maximum prompts limit reached ({self._max_prompts})")

        row = await MemoPrompt.create(
            user_id=user_id, platform=platform, title=title, content=content
        )
        prompt_id = row["id"]
        logger.info(f"Created prompt {prompt_id}: {title}")
        return prompt_id

    async def get_prompt(self, prompt_id: int, user_id: int) -> dict | None:
        """Get a prompt by ID."""
        from plugins.memo.models import MemoPrompt

        results = await MemoPrompt.search(
            [("id", "=", prompt_id), ("user_id", "=", user_id)], limit=1
        )
        return dict(results[0]) if results else None

    async def update_prompt(
        self,
        prompt_id: int,
        user_id: int,
        title: str | None = None,
        content: str | None = None,
    ) -> bool:
        """Update a prompt."""
        from plugins.memo.models import MemoPrompt

        updates = {}
        if title is not None:
            updates["title"] = title
        if content is not None:
            updates["content"] = content
        if not updates:
            return False

        # auto_now on updated_at handles the timestamp
        # Use write_multi to enforce user_id ownership
        updated = await MemoPrompt.write_multi(
            [("id", "=", prompt_id), ("user_id", "=", user_id)],
            **updates,
        )
        return updated > 0

    async def delete_prompt(self, prompt_id: int, user_id: int) -> bool:
        """Delete a prompt and all its scheduled memos."""
        from plugins.memo.models import MemoPrompt, ScheduledMemo

        # Find associated memos to remove APScheduler jobs
        memo_rows = await ScheduledMemo.search(
            [("prompt_id", "=", prompt_id), ("user_id", "=", user_id)]
        )
        for row in memo_rows:
            try:
                self.scheduler.remove_job(f"memo_{row['id']}")
            except Exception:
                pass

        # CASCADE on FK handles scheduled_memos deletion
        deleted = await MemoPrompt.delete_multi(
            [("id", "=", prompt_id), ("user_id", "=", user_id)]
        )
        return deleted > 0

    async def list_prompts(self, user_id: int, platform: str) -> list[dict]:
        """List all prompts for a user (with schedule count)."""
        from plugins.memo.models import MemoPrompt

        rows = await MemoPrompt.raw_search(
            "SELECT p.*, "
            "(SELECT COUNT(*) FROM app.scheduled_memos WHERE prompt_id = p.id) as schedule_count "
            "FROM {table} p "
            "WHERE p.user_id = %s AND p.platform = %s "
            "ORDER BY p.created_at DESC",
            (user_id, platform),
        )
        return [dict(r) for r in rows]

    async def count_prompts(self, user_id: int, platform: str) -> int:
        """Count prompts for a user."""
        from plugins.memo.models import MemoPrompt

        return await MemoPrompt.count(
            [("user_id", "=", user_id), ("platform", "=", platform)]
        )

    # ========== MEMO (SCHEDULE) METHODS ==========

    async def create_memo(
        self,
        user_id: int,
        platform: str,
        prompt_id: int,
        schedule_type: str,
        cron: str | None = None,
        run_at: datetime | None = None,
    ) -> int:
        """Create a new scheduled memo referencing a prompt."""
        from plugins.memo.models import ScheduledMemo

        if self._max_memos > 0:
            count = await self.count_memos(user_id, platform)
            if count >= self._max_memos:
                raise ValueError(f"Maximum memos limit reached ({self._max_memos})")

        # Verify prompt exists and belongs to user
        prompt = await self.get_prompt(prompt_id, user_id)
        if not prompt:
            raise ValueError(f"Prompt {prompt_id} not found")

        row = await ScheduledMemo.create(
            user_id=user_id,
            platform=platform,
            prompt_id=prompt_id,
            schedule_type=schedule_type,
            cron=cron,
            run_at=run_at.isoformat() if run_at else None,
        )
        memo_id = row["id"]

        # Schedule the job
        memo = {
            "id": memo_id,
            "user_id": user_id,
            "platform": platform,
            "prompt_id": prompt_id,
            "schedule_type": schedule_type,
            "cron": cron,
            "run_at": run_at.isoformat() if run_at else None,
            "prompt_content": prompt["content"],
            "prompt_title": prompt["title"],
        }
        self._add_job(memo)

        logger.info(f"Created memo {memo_id} with prompt {prompt_id}")
        return memo_id

    async def add_memo(
        self,
        user_id: int,
        platform: str,
        schedule_type: str,
        prompt: str,
        description: str,
        cron: str | None = None,
        run_at: datetime | None = None,
    ) -> int:
        """Add a new memo (creates prompt and schedule in one step).

        This is a convenience method that creates both the prompt and schedule.
        """
        # Create prompt first
        title = description[:50] if description else prompt[:50]
        prompt_id = await self.create_prompt(user_id, platform, title, prompt)

        # Create scheduled memo
        return await self.create_memo(
            user_id=user_id,
            platform=platform,
            prompt_id=prompt_id,
            schedule_type=schedule_type,
            cron=cron,
            run_at=run_at,
        )

    # Alias for backwards compatibility
    async def add_task(self, **kwargs) -> int:
        """Alias for add_memo (backwards compatibility)."""
        return await self.add_memo(**kwargs)

    async def list_memos(self, user_id: int, platform: str) -> list[dict]:
        """List all memos for a user with prompt details."""
        from plugins.memo.models import ScheduledMemo

        rows = await ScheduledMemo.raw_search(
            "SELECT m.*, p.title as prompt_title, p.content as prompt_content "
            "FROM {table} m "
            "JOIN app.memo_prompts p ON m.prompt_id = p.id "
            "WHERE m.user_id = %s AND m.platform = %s "
            "ORDER BY m.created_at DESC",
            (user_id, platform),
        )
        return [dict(r) for r in rows]

    # Alias for backwards compatibility
    async def list_tasks(self, user_id: int, platform: str) -> list[dict]:
        """Alias for list_memos (backwards compatibility)."""
        return await self.list_memos(user_id, platform)

    async def count_memos(self, user_id: int, platform: str) -> int:
        """Count memos for a user."""
        from plugins.memo.models import ScheduledMemo

        return await ScheduledMemo.count(
            [("user_id", "=", user_id), ("platform", "=", platform)]
        )

    async def delete_memo(self, memo_id: int, user_id: int) -> bool:
        """Delete a memo schedule (keeps the prompt)."""
        from plugins.memo.models import ScheduledMemo

        deleted = await ScheduledMemo.delete_multi(
            [("id", "=", memo_id), ("user_id", "=", user_id)]
        )

        if deleted > 0:
            try:
                self.scheduler.remove_job(f"memo_{memo_id}")
            except Exception:
                pass
            logger.info(f"Deleted memo {memo_id}")

        return deleted > 0

    # Alias for backwards compatibility
    async def delete_task(self, task_id: int, user_id: int) -> bool:
        """Alias for delete_memo (backwards compatibility)."""
        return await self.delete_memo(task_id, user_id)

    async def toggle_memo(self, memo_id: int, user_id: int) -> bool | None:
        """Toggle memo enabled/disabled. Returns new state or None if not found."""
        from plugins.memo.models import ScheduledMemo

        rows = await ScheduledMemo.raw_search(
            "SELECT m.*, p.content as prompt_content, p.title as prompt_title "
            "FROM {table} m "
            "JOIN app.memo_prompts p ON m.prompt_id = p.id "
            "WHERE m.id = %s AND m.user_id = %s",
            (memo_id, user_id),
        )
        if not rows:
            return None
        memo = dict(rows[0])

        new_state = not memo["enabled"]
        await ScheduledMemo.write(memo_id, enabled=new_state)

        job_id = f"memo_{memo_id}"
        if new_state:
            self._add_job(memo)
        else:
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass

        return new_state

    # Alias for backwards compatibility
    async def toggle_task(self, task_id: int, user_id: int) -> bool | None:
        """Alias for toggle_memo (backwards compatibility)."""
        return await self.toggle_memo(task_id, user_id)

    async def get_all_memos(self) -> list[dict]:
        """Get all memos (for admin)."""
        from plugins.memo.models import ScheduledMemo

        rows = await ScheduledMemo.raw_search(
            "SELECT m.*, p.title as prompt_title, p.content as prompt_content "
            "FROM {table} m "
            "JOIN app.memo_prompts p ON m.prompt_id = p.id "
            "ORDER BY m.created_at DESC",
        )
        return [dict(r) for r in rows]

    async def get_all_prompts(self) -> list[dict]:
        """Get all prompts (for admin)."""
        from plugins.memo.models import MemoPrompt

        rows = await MemoPrompt.raw_search(
            "SELECT p.*, "
            "(SELECT COUNT(*) FROM app.scheduled_memos WHERE prompt_id = p.id) as schedule_count "
            "FROM {table} p "
            "ORDER BY p.created_at DESC",
        )
        return [dict(r) for r in rows]
