"""Async task manager for long-running MCP tool calls."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from config.logging_config import logger


@dataclass
class AsyncTask:
    """A background task wrapping a long-running MCP tool call."""

    id: str
    tool_name: str
    agent_name: str
    status: str = "running"  # running, completed, failed
    result: list[dict] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    notify_chat_id: str | None = None
    notify_platform: str | None = None


class AsyncTaskManager:
    """Manages background execution of long-running MCP tool calls."""

    CLEANUP_INTERVAL = 600  # 10 minutes
    TASK_MAX_AGE = 3600  # 1 hour

    def __init__(
        self,
        notify_callback: Callable[[AsyncTask], Coroutine] | None = None,
        max_concurrent_per_agent: int = 5,
    ):
        self._tasks: dict[str, AsyncTask] = {}
        self._asyncio_tasks: dict[str, asyncio.Task] = {}
        self._notify_callback = notify_callback
        self._max_concurrent_per_agent = max_concurrent_per_agent
        self._cleanup_task: asyncio.Task | None = None

    async def start(self):
        """Start the cleanup loop."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("AsyncTaskManager started")

    async def shutdown(self):
        """Cancel cleanup loop and all active tasks."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None

        for task_id, atask in list(self._asyncio_tasks.items()):
            if not atask.done():
                atask.cancel()
                logger.info("AsyncTaskManager: cancelled task %s", task_id)

        self._asyncio_tasks.clear()
        logger.info(
            "AsyncTaskManager shut down (%d tasks in registry)", len(self._tasks)
        )

    async def submit(
        self,
        tool_name: str,
        coro: Coroutine,
        agent_name: str,
        notify_chat_id: str | None = None,
        notify_platform: str | None = None,
    ) -> str:
        """Submit a coroutine for background execution. Returns task_id."""
        # Check per-agent concurrency limit
        running = sum(
            1
            for t in self._tasks.values()
            if t.agent_name == agent_name and t.status == "running"
        )
        if running >= self._max_concurrent_per_agent:
            raise RuntimeError(
                f"Agent '{agent_name}' has reached the maximum of "
                f"{self._max_concurrent_per_agent} concurrent async tasks. "
                f"Wait for a task to complete or check status with async_list_tasks."
            )

        task_id = f"task-{uuid.uuid4().hex[:8]}"
        task = AsyncTask(
            id=task_id,
            tool_name=tool_name,
            agent_name=agent_name,
            notify_chat_id=notify_chat_id,
            notify_platform=notify_platform,
        )
        self._tasks[task_id] = task
        self._asyncio_tasks[task_id] = asyncio.create_task(
            self._task_wrapper(task_id, coro)
        )
        logger.info(
            "AsyncTask submitted: id=%s tool=%s agent=%s (%d/%d running)",
            task_id,
            tool_name,
            agent_name,
            running + 1,
            self._max_concurrent_per_agent,
        )
        return task_id

    def get_status(self, task_id: str, agent_name: str) -> dict | None:
        """Get task status, filtered by agent ownership."""
        task = self._tasks.get(task_id)
        if not task or task.agent_name != agent_name:
            return None
        return self._task_to_dict(task)

    def list_tasks(
        self,
        agent_name: str,
        status_filter: str | None = None,
    ) -> list[dict]:
        """List tasks for an agent, optionally filtered by status."""
        result = []
        for task in self._tasks.values():
            if task.agent_name != agent_name:
                continue
            if status_filter and task.status != status_filter:
                continue
            result.append(self._task_to_dict(task))
        return result

    def cancel_tasks_by_agent(self, agent_name: str) -> int:
        """Cancel all running async tasks for an agent. Returns count cancelled."""
        cancelled = 0
        for task_id, atask in list(self._asyncio_tasks.items()):
            task = self._tasks.get(task_id)
            if task and task.agent_name == agent_name and not atask.done():
                atask.cancel()
                cancelled += 1
                logger.info("Cancelled async task %s for agent %s", task_id, agent_name)
        return cancelled

    async def _task_wrapper(self, task_id: str, coro: Coroutine):
        """Execute coroutine, store result, and send notification."""
        task = self._tasks[task_id]
        try:
            result = await coro
            task.status = "completed"
            task.result = result
        except asyncio.CancelledError:
            task.status = "failed"
            task.error = "Task was cancelled"
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.error("AsyncTask %s failed: %s", task_id, e)
        finally:
            task.completed_at = time.time()
            self._asyncio_tasks.pop(task_id, None)

        # Send notification
        if self._notify_callback and task.notify_chat_id:
            try:
                await self._notify_callback(task)
            except Exception as e:
                logger.error("AsyncTask notification failed for %s: %s", task_id, e)

    async def _cleanup_loop(self):
        """Periodically remove old completed/failed tasks."""
        while True:
            await asyncio.sleep(self.CLEANUP_INTERVAL)
            try:
                now = time.time()
                to_remove = [
                    tid
                    for tid, t in self._tasks.items()
                    if t.status in ("completed", "failed")
                    and t.completed_at
                    and (now - t.completed_at) > self.TASK_MAX_AGE
                ]
                for tid in to_remove:
                    del self._tasks[tid]
                if to_remove:
                    logger.info(
                        "AsyncTask cleanup: removed %d old tasks", len(to_remove)
                    )
            except Exception as e:
                logger.warning("AsyncTask cleanup error: %s", e)

    @staticmethod
    def _task_to_dict(task: AsyncTask) -> dict:
        """Convert task to a serializable dict."""
        d: dict[str, Any] = {
            "task_id": task.id,
            "tool_name": task.tool_name,
            "status": task.status,
            "created_at": task.created_at,
        }
        if task.completed_at:
            d["completed_at"] = task.completed_at
            d["duration_seconds"] = round(task.completed_at - task.created_at, 1)
        if task.status == "completed" and task.result:
            # Include a summary (first 500 chars of first text content)
            for item in task.result:
                if item.get("type") == "text":
                    text = item["text"]
                    d["result_summary"] = text[:500] + (
                        "..." if len(text) > 500 else ""
                    )
                    break
        if task.error:
            d["error"] = task.error
        return d
