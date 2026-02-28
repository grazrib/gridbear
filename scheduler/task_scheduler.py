"""Task Scheduler - Manages scheduled tasks with persistence (PostgreSQL)."""

from datetime import datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from config.logging_config import logger

TIMEZONE = ZoneInfo("Europe/Rome")


class TaskScheduler:
    """Manages scheduled tasks with persistence."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=TIMEZONE)
        self._callback: Callable[[int, str, str, str], Awaitable[None]] | None = None

    async def initialize(self) -> None:
        """Initialize scheduler and load persisted tasks."""
        await self._load_tasks()
        self.scheduler.start()
        logger.info("Task scheduler initialized (PostgreSQL)")

    async def shutdown(self) -> None:
        """Shutdown scheduler gracefully."""
        self.scheduler.shutdown(wait=True)
        logger.info("Task scheduler shutdown")

    def set_callback(
        self, callback: Callable[[int, str, str, str], Awaitable[None]]
    ) -> None:
        """Set callback for task execution: callback(task_id, user_id, platform, prompt)."""
        self._callback = callback

    async def _load_tasks(self) -> None:
        """Load persisted tasks and schedule them."""
        from scheduler.models import ScheduledTask

        rows = await ScheduledTask.search([("enabled", "=", True)])
        for task in rows:
            self._add_job(dict(task))
        logger.info(f"Loaded {len(rows)} scheduled tasks")

    def _add_job(self, task: dict) -> None:
        """Add a job to the scheduler."""
        job_id = f"task_{task['id']}"

        if task["schedule_type"] == "cron" and task["cron"]:
            parts = task["cron"].split()
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            )
        elif task["schedule_type"] == "once" and task["run_at"]:
            run_at = datetime.fromisoformat(task["run_at"])
            if run_at <= datetime.now(TIMEZONE):
                logger.debug(f"Skipping past task {job_id}")
                return
            trigger = DateTrigger(run_date=run_at)
        else:
            logger.warning(f"Invalid task configuration: {task}")
            return

        self.scheduler.add_job(
            self._execute_task,
            trigger=trigger,
            id=job_id,
            args=[task["id"], task["user_id"], task["platform"], task["prompt"]],
            replace_existing=True,
        )
        logger.debug(f"Scheduled job {job_id}: {task['description']}")

    async def _execute_task(
        self, task_id: int, user_id: int, platform: str, prompt: str
    ) -> None:
        """Execute a scheduled task."""
        from scheduler.models import ScheduledTask

        logger.info(f"Executing scheduled task {task_id} for user {user_id}")

        # Update last_run
        await ScheduledTask.write(task_id, last_run=datetime.now(TIMEZONE))

        # Call the callback
        if self._callback:
            try:
                await self._callback(task_id, user_id, platform, prompt)
            except Exception as e:
                logger.error(f"Error executing task {task_id}: {e}")

        # Check if one-time task, disable it
        rows = await ScheduledTask.search([("id", "=", task_id)], limit=1)
        if rows and rows[0]["schedule_type"] == "once":
            await ScheduledTask.write(task_id, enabled=False)

    async def add_task(
        self,
        user_id: int,
        platform: str,
        schedule_type: str,
        prompt: str,
        description: str,
        cron: str | None = None,
        run_at: datetime | None = None,
    ) -> int:
        """Add a new scheduled task."""
        from scheduler.models import ScheduledTask

        row = await ScheduledTask.create(
            user_id=user_id,
            platform=platform,
            schedule_type=schedule_type,
            cron=cron,
            run_at=run_at.isoformat() if run_at else None,
            prompt=prompt,
            description=description,
        )
        task_id = row["id"]

        # Schedule the job
        task = {
            "id": task_id,
            "user_id": user_id,
            "platform": platform,
            "schedule_type": schedule_type,
            "cron": cron,
            "run_at": run_at.isoformat() if run_at else None,
            "prompt": prompt,
            "description": description,
        }
        self._add_job(task)

        logger.info(f"Added task {task_id}: {description}")
        return task_id

    async def list_tasks(self, user_id: int, platform: str) -> list[dict]:
        """List all tasks for a user."""
        from scheduler.models import ScheduledTask

        rows = await ScheduledTask.search(
            [("user_id", "=", user_id), ("platform", "=", platform)],
            order="created_at DESC",
        )
        return [dict(r) for r in rows]

    async def delete_task(self, task_id: int, user_id: int) -> bool:
        """Delete a task (only if owned by user)."""
        from scheduler.models import ScheduledTask

        deleted = await ScheduledTask.delete_multi(
            [("id", "=", task_id), ("user_id", "=", user_id)]
        )

        if deleted > 0:
            job_id = f"task_{task_id}"
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass
            logger.info(f"Deleted task {task_id}")

        return deleted > 0

    async def toggle_task(self, task_id: int, user_id: int) -> bool | None:
        """Toggle task enabled/disabled. Returns new state or None if not found."""
        from scheduler.models import ScheduledTask

        rows = await ScheduledTask.search(
            [("id", "=", task_id), ("user_id", "=", user_id)],
            limit=1,
        )
        if not rows:
            return None

        new_state = not rows[0]["enabled"]
        await ScheduledTask.write(task_id, enabled=new_state)

        job_id = f"task_{task_id}"
        if new_state:
            # Re-load and schedule
            fresh = await ScheduledTask.search([("id", "=", task_id)], limit=1)
            if fresh:
                self._add_job(dict(fresh[0]))
        else:
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass

        return new_state
