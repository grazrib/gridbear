"""Planner service for Microsoft 365 plugin."""

from typing import Any

from .graph_client import GraphClient


class PlannerService:
    """Service for Microsoft Planner operations via Microsoft Graph."""

    def __init__(self, graph_client: GraphClient):
        """Initialize Planner service.

        Args:
            graph_client: Graph API client instance
        """
        self.client = graph_client

    async def list_plans(
        self,
        token: str,
        group_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List Planner plans accessible to the user.

        Args:
            token: Access token
            group_id: Filter by group ID (optional)

        Returns:
            List of plan dicts
        """
        if group_id:
            endpoint = f"/groups/{group_id}/planner/plans"
        else:
            endpoint = "/me/planner/plans"

        result = await self.client.get(endpoint, token)

        if isinstance(result, dict) and "value" in result:
            return [
                {
                    "id": plan["id"],
                    "title": plan.get("title", ""),
                    "owner": plan.get("owner", ""),
                    "created": plan.get("createdDateTime", ""),
                }
                for plan in result["value"]
            ]
        return []

    async def get_plan(self, token: str, plan_id: str) -> dict[str, Any] | None:
        """Get plan details.

        Args:
            token: Access token
            plan_id: Plan ID

        Returns:
            Plan details or None
        """
        result = await self.client.get(f"/planner/plans/{plan_id}", token)

        if isinstance(result, dict):
            return {
                "id": result.get("id", ""),
                "title": result.get("title", ""),
                "owner": result.get("owner", ""),
                "created": result.get("createdDateTime", ""),
            }
        return None

    async def list_buckets(self, token: str, plan_id: str) -> list[dict[str, Any]]:
        """List buckets in a plan.

        Args:
            token: Access token
            plan_id: Plan ID

        Returns:
            List of bucket dicts
        """
        result = await self.client.get(f"/planner/plans/{plan_id}/buckets", token)

        if isinstance(result, dict) and "value" in result:
            return [
                {
                    "id": bucket["id"],
                    "name": bucket.get("name", ""),
                    "order_hint": bucket.get("orderHint", ""),
                }
                for bucket in result["value"]
            ]
        return []

    async def list_tasks(
        self,
        token: str,
        plan_id: str,
        bucket_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks in a plan or bucket.

        Args:
            token: Access token
            plan_id: Plan ID
            bucket_id: Filter by bucket ID (optional)

        Returns:
            List of task dicts
        """
        endpoint = f"/planner/plans/{plan_id}/tasks"
        result = await self.client.get(endpoint, token)

        if isinstance(result, dict) and "value" in result:
            tasks = result["value"]

            # Filter by bucket if specified
            if bucket_id:
                tasks = [t for t in tasks if t.get("bucketId") == bucket_id]

            return [
                {
                    "id": task["id"],
                    "title": task.get("title", ""),
                    "bucket_id": task.get("bucketId", ""),
                    "percent_complete": task.get("percentComplete", 0),
                    "due_date": task.get("dueDateTime", ""),
                    "priority": task.get("priority", 5),
                    "assigned_to": list(task.get("assignments", {}).keys()),
                    "created": task.get("createdDateTime", ""),
                }
                for task in tasks
            ]
        return []

    async def get_task(self, token: str, task_id: str) -> dict[str, Any] | None:
        """Get task details including description.

        Args:
            token: Access token
            task_id: Task ID

        Returns:
            Task details or None
        """
        # Get basic task info
        task = await self.client.get(f"/planner/tasks/{task_id}", token)

        if not isinstance(task, dict):
            return None

        # Get task details (description, checklist)
        details = await self.client.get(f"/planner/tasks/{task_id}/details", token)

        result = {
            "id": task.get("id", ""),
            "title": task.get("title", ""),
            "bucket_id": task.get("bucketId", ""),
            "plan_id": task.get("planId", ""),
            "percent_complete": task.get("percentComplete", 0),
            "due_date": task.get("dueDateTime", ""),
            "start_date": task.get("startDateTime", ""),
            "priority": task.get("priority", 5),
            "assigned_to": list(task.get("assignments", {}).keys()),
            "created": task.get("createdDateTime", ""),
        }

        if isinstance(details, dict):
            result["description"] = details.get("description", "")
            result["checklist"] = [
                {
                    "id": k,
                    "title": v.get("title", ""),
                    "is_checked": v.get("isChecked", False),
                }
                for k, v in details.get("checklist", {}).items()
            ]

        return result

    async def create_task(
        self,
        token: str,
        plan_id: str,
        title: str,
        bucket_id: str | None = None,
        due_date: str | None = None,
        assigned_to: list[str] | None = None,
        priority: int = 5,
    ) -> dict[str, Any] | None:
        """Create a new task.

        Args:
            token: Access token
            plan_id: Plan ID
            title: Task title
            bucket_id: Bucket ID (optional)
            due_date: Due date ISO string (optional)
            assigned_to: List of user IDs to assign (optional)
            priority: Priority 0-10 (5 is normal)

        Returns:
            Created task or None
        """
        body: dict[str, Any] = {
            "planId": plan_id,
            "title": title,
            "priority": priority,
        }

        if bucket_id:
            body["bucketId"] = bucket_id

        if due_date:
            body["dueDateTime"] = due_date

        if assigned_to:
            body["assignments"] = {
                user_id: {
                    "@odata.type": "#microsoft.graph.plannerAssignment",
                    "orderHint": " !",
                }
                for user_id in assigned_to
            }

        result = await self.client.post("/planner/tasks", token, json_data=body)

        if isinstance(result, dict):
            return {
                "id": result.get("id", ""),
                "title": result.get("title", ""),
                "bucket_id": result.get("bucketId", ""),
                "plan_id": result.get("planId", ""),
            }
        return None

    async def update_task(
        self,
        token: str,
        task_id: str,
        updates: dict[str, Any],
    ) -> bool:
        """Update a task.

        Args:
            token: Access token
            task_id: Task ID
            updates: Fields to update (title, percentComplete, dueDateTime, priority)

        Returns:
            True if successful
        """
        # Get current task for ETag
        current = await self.client.get(f"/planner/tasks/{task_id}", token)
        if not isinstance(current, dict):
            return False

        etag = current.get("@odata.etag", "")

        # Map friendly names to API names
        field_map = {
            "title": "title",
            "percent_complete": "percentComplete",
            "due_date": "dueDateTime",
            "start_date": "startDateTime",
            "priority": "priority",
            "bucket_id": "bucketId",
        }

        body = {}
        for key, value in updates.items():
            api_key = field_map.get(key, key)
            body[api_key] = value

        # PATCH requires If-Match header
        client = await self.client._get_client()
        response = await client.patch(
            f"/planner/tasks/{task_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "If-Match": etag,
                "Content-Type": "application/json",
            },
            json=body,
        )

        return response.status_code in (200, 204)

    async def complete_task(self, token: str, task_id: str) -> bool:
        """Mark a task as complete (100%).

        Args:
            token: Access token
            task_id: Task ID

        Returns:
            True if successful
        """
        return await self.update_task(token, task_id, {"percent_complete": 100})

    async def update_task_details(
        self,
        token: str,
        task_id: str,
        description: str | None = None,
    ) -> bool:
        """Update task details (description).

        Args:
            token: Access token
            task_id: Task ID
            description: New description

        Returns:
            True if successful
        """
        # Get current details for ETag
        current = await self.client.get(f"/planner/tasks/{task_id}/details", token)
        if not isinstance(current, dict):
            return False

        etag = current.get("@odata.etag", "")

        body = {}
        if description is not None:
            body["description"] = description

        if not body:
            return True

        client = await self.client._get_client()
        response = await client.patch(
            f"/planner/tasks/{task_id}/details",
            headers={
                "Authorization": f"Bearer {token}",
                "If-Match": etag,
                "Content-Type": "application/json",
            },
            json=body,
        )

        return response.status_code in (200, 204)

    async def delete_task(self, token: str, task_id: str) -> bool:
        """Delete a task.

        Args:
            token: Access token
            task_id: Task ID

        Returns:
            True if successful
        """
        # Get current task for ETag
        current = await self.client.get(f"/planner/tasks/{task_id}", token)
        if not isinstance(current, dict):
            return False

        etag = current.get("@odata.etag", "")

        client = await self.client._get_client()
        response = await client.delete(
            f"/planner/tasks/{task_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "If-Match": etag,
            },
        )

        return response.status_code == 204
