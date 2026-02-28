"""Microsoft 365 plugin for GridBear - Entry point."""

import asyncio
import os
import re
from typing import Any

from config.logging_config import logger
from config.settings import get_unified_user_id
from core.hooks import HookData, hook_manager
from core.interfaces.service import BaseService

from .auth import OAuthManager, TokenStore
from .context import get_context
from .services import GraphClient, OneDriveService, PlannerService, SharePointService


class MS365Plugin(BaseService):
    """Microsoft 365 integration plugin for GridBear."""

    name = "ms365"

    def __init__(self, config: dict):
        super().__init__(config)
        self.config = config

        # Components (initialized in initialize())
        self.token_store: TokenStore | None = None
        self.oauth_manager: OAuthManager | None = None
        self.graph_client: GraphClient | None = None
        self.sharepoint: SharePointService | None = None
        self.planner: PlannerService | None = None
        self.onedrive: OneDriveService | None = None

        # Results storage for context injection
        self._last_command_results: dict[str, list[str]] = {}

        # Health check task
        self._health_check_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        """Initialize the plugin."""
        logger.info("Initializing MS365 plugin")

        # Get configuration
        client_id = self.config.get("client_id", "")
        client_secret_env = self.config.get("client_secret_env", "MS365_CLIENT_SECRET")
        client_secret = os.environ.get(client_secret_env, "")
        redirect_uri = self.config.get(
            "redirect_uri", "http://localhost:8080/auth/ms365/callback"
        )
        encryption_key_env = self.config.get(
            "encryption_key_env", "MS365_ENCRYPTION_KEY"
        )
        encryption_key = os.environ.get(encryption_key_env)

        if not client_id:
            logger.warning("MS365: client_id not configured")
            return

        if not client_secret:
            logger.warning(f"MS365: {client_secret_env} not set")

        # Initialize token store
        self.token_store = TokenStore(encryption_key=encryption_key)

        # Initialize OAuth manager
        self.oauth_manager = OAuthManager(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            token_store=self.token_store,
        )

        # Initialize Graph client and services
        self.graph_client = GraphClient()
        self.sharepoint = SharePointService(self.graph_client)
        self.planner = PlannerService(self.graph_client)
        self.onedrive = OneDriveService(self.graph_client)

        # Register hooks
        hook_manager.register(
            "after_context_build",
            self._inject_tenant_context_hook,
            priority=10,
            plugin_name="ms365",
        )

        hook_manager.register(
            "after_context_build",
            self._inject_previous_results_hook,
            priority=5,
            plugin_name="ms365",
        )

        hook_manager.register(
            "after_runner_call",
            self._process_response_hook,
            priority=10,
            plugin_name="ms365",
        )

        # Start health check task
        health_interval = self.config.get("health_check_interval", 300)
        self._health_check_task = asyncio.create_task(
            self._health_check_loop(health_interval)
        )

        tenant_count = len(self.token_store.get_all_tenants())
        logger.info(f"MS365 plugin initialized with {tenant_count} tenants")

    async def shutdown(self) -> None:
        """Shutdown the plugin."""
        hook_manager.unregister("after_context_build", self._inject_tenant_context_hook)
        hook_manager.unregister(
            "after_context_build", self._inject_previous_results_hook
        )
        hook_manager.unregister("after_runner_call", self._process_response_hook)

        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        if self.graph_client:
            await self.graph_client.close()

        logger.info("MS365 plugin shutdown complete")

    def get_context(self) -> str:
        """Return context for injection."""
        return get_context()

    # ========== Health Check ==========

    async def _health_check_loop(self, interval: int) -> None:
        """Periodic health check for all tenants."""
        while True:
            try:
                await asyncio.sleep(interval)
                await self._check_all_tenants()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"MS365 health check error: {e}")

    async def _check_all_tenants(self) -> None:
        """Check health of all tenants."""
        if not self.token_store or not self.oauth_manager:
            return

        tenants = self.token_store.get_all_tenants()

        for tenant in tenants:
            tenant_id = tenant["tenant_id"]
            try:
                token = await self.oauth_manager.get_valid_token(tenant_id)
                if token:
                    # Simple check - get user profile
                    await self.graph_client.get_me(token)
                    self.token_store.mark_active(tenant_id)
                    logger.debug(f"MS365: Tenant {tenant['tenant_name']} healthy")
            except Exception as e:
                logger.warning(
                    f"MS365: Tenant {tenant['tenant_name']} health check failed: {e}"
                )
                self.token_store.mark_failure(tenant_id)

    # ========== Hook Handlers ==========

    async def _inject_tenant_context_hook(
        self, hook_data: HookData, **kwargs
    ) -> HookData:
        """Inject tenant-specific context into prompt."""
        if not hook_data.username or not self.token_store:
            return hook_data

        tenants = self.token_store.get_all_tenants()
        if not tenants:
            return hook_data

        # Build tenant context
        lines = ["\n[Your Microsoft 365 Tenants]"]

        for tenant in tenants:
            status = tenant["status"]
            status_icon = "online" if status == "active" else "offline"
            role = tenant["role"]

            lines.append(f"\n**{tenant['tenant_name']}** ({role}) - {status_icon}")

            caps = tenant.get("capabilities")
            if caps:
                cached_at = tenant.get("capabilities_cached_at", "")
                lines.append(f"  cached: {cached_at}")

                if caps.get("sharepoint", {}).get("available"):
                    sites = caps["sharepoint"].get("sites", [])
                    lines.append(f"  - SharePoint: {len(sites)} site(s)")

                if caps.get("planner", {}).get("available"):
                    plans = caps["planner"].get("plans", [])
                    lines.append(f"  - Planner: {len(plans)} plan(s)")

                if caps.get("onedrive", {}).get("available"):
                    lines.append("  - OneDrive: Available")

        if len(lines) > 1:
            hook_data.prompt += "\n".join(lines)
            logger.debug(f"MS365: Injected context with {len(tenants)} tenants")

        return hook_data

    async def _inject_previous_results_hook(
        self, hook_data: HookData, **kwargs
    ) -> HookData:
        """Inject previous command results into context."""
        if not hook_data.username:
            return hook_data

        unified_id = get_unified_user_id(hook_data.platform, hook_data.username.lower())
        if not unified_id:
            return hook_data

        previous_results = self._last_command_results.pop(unified_id, None)
        if previous_results:
            results_text = "\n".join(previous_results)
            injection = (
                f"\n\n[Previous MS365 Command Results]\n"
                f"Results from Microsoft 365 commands:\n"
                f"{results_text}\n"
            )
            hook_data.prompt += injection
            logger.debug(f"MS365: Injected {len(previous_results)} previous results")

        return hook_data

    async def _process_response_hook(self, hook_data: HookData, **kwargs) -> HookData:
        """Process M365_* tags in Claude responses."""
        if not hook_data.response_text:
            return hook_data

        tag_types = [
            "M365_LIST_SITES",
            "M365_LIST_FILES",
            "M365_READ_FILE",
            "M365_WRITE_FILE",
            "M365_SEARCH_FILES",
            "M365_LIST_PLANS",
            "M365_LIST_TASKS",
            "M365_GET_TASK",
            "M365_CREATE_TASK",
            "M365_UPDATE_TASK",
            "M365_COMPLETE_TASK",
            "M365_LIST_DRIVE_FILES",
            "M365_READ_DRIVE_FILE",
            "M365_WRITE_DRIVE_FILE",
        ]

        has_tags = any(f"[{tag}" in hook_data.response_text for tag in tag_types)
        if not has_tags:
            return hook_data

        unified_id = None
        if hook_data.username:
            unified_id = get_unified_user_id(
                hook_data.platform, hook_data.username.lower()
            )

        if not unified_id:
            logger.warning("MS365: Cannot process tags without user context")
            return hook_data

        all_results = []

        # Process each tag type
        all_results.extend(await self._process_list_sites_tags(hook_data.response_text))
        all_results.extend(await self._process_list_files_tags(hook_data.response_text))
        all_results.extend(await self._process_read_file_tags(hook_data.response_text))
        all_results.extend(await self._process_write_file_tags(hook_data.response_text))
        all_results.extend(await self._process_list_plans_tags(hook_data.response_text))
        all_results.extend(await self._process_list_tasks_tags(hook_data.response_text))
        all_results.extend(
            await self._process_create_task_tags(hook_data.response_text)
        )
        all_results.extend(
            await self._process_complete_task_tags(hook_data.response_text)
        )
        all_results.extend(await self._process_drive_tags(hook_data.response_text))

        if all_results:
            results_text = "\n\n---\n**MS365 Results:**\n" + "\n".join(all_results)
            hook_data.response_text += results_text
            self._last_command_results[unified_id] = all_results
            logger.debug(f"MS365: Stored {len(all_results)} results for {unified_id}")

        return hook_data

    # ========== Tag Processing ==========

    async def _get_token_for_tenant(self, tenant_name: str) -> str | None:
        """Get valid token for tenant by name."""
        if not self.token_store or not self.oauth_manager:
            return None

        tenants = self.token_store.get_all_tenants()
        for tenant in tenants:
            if tenant["tenant_name"].lower() == tenant_name.lower():
                return await self.oauth_manager.get_valid_token(tenant["tenant_id"])
        return None

    async def _process_list_sites_tags(self, text: str) -> list[str]:
        """Process [M365_LIST_SITES] tags."""
        results = []
        pattern = r'\[M365_LIST_SITES(?:\s+tenant="([^"]+)")?\]'

        for match in re.finditer(pattern, text):
            tenant_name = match.group(1) or "default"

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token available for tenant {tenant_name}")
                    continue

                sites = await self.sharepoint.list_sites(token)
                if sites:
                    lines = [f"**SharePoint Sites ({tenant_name}):**"]
                    for site in sites[:15]:
                        lines.append(f"- {site['name']} (ID: {site['id'][:20]}...)")
                    results.append("\n".join(lines))
                else:
                    results.append(f"No SharePoint sites found for {tenant_name}")
            except Exception as e:
                results.append(f"Error listing sites: {e}")

        return results

    async def _process_list_files_tags(self, text: str) -> list[str]:
        """Process [M365_LIST_FILES] tags."""
        results = []
        pattern = r'\[M365_LIST_FILES\s+tenant="([^"]+)"\s+site_id="([^"]+)"(?:\s+folder_path="([^"]*)")?\]'

        for match in re.finditer(pattern, text):
            tenant_name = match.group(1)
            site_id = match.group(2)
            folder_path = match.group(3) or ""

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token for tenant {tenant_name}")
                    continue

                files = await self.sharepoint.list_files(
                    token, site_id, folder_path=folder_path
                )
                if files:
                    lines = [f"**Files in {folder_path or '/'}:**"]
                    for f in files[:20]:
                        icon = "folder" if f["type"] == "folder" else "file"
                        size = f"{f['size'] // 1024}KB" if f["type"] == "file" else ""
                        lines.append(f"- [{icon}] {f['name']} {size}")
                    results.append("\n".join(lines))
                else:
                    results.append("No files found")
            except Exception as e:
                results.append(f"Error listing files: {e}")

        return results

    async def _process_read_file_tags(self, text: str) -> list[str]:
        """Process [M365_READ_FILE] tags."""
        results = []
        pattern = r'\[M365_READ_FILE\s+tenant="([^"]+)"\s+site_id="([^"]+)"\s+file_path="([^"]+)"\]'

        for match in re.finditer(pattern, text):
            tenant_name = match.group(1)
            site_id = match.group(2)
            file_path = match.group(3)

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token for tenant {tenant_name}")
                    continue

                content = await self.sharepoint.read_file_text(
                    token, site_id, file_path
                )
                if content:
                    if len(content) > 5000:
                        content = content[:5000] + "\n...(truncated)"
                    results.append(f"**File: {file_path}**\n```\n{content}\n```")
                else:
                    results.append(f"Could not read file: {file_path}")
            except Exception as e:
                results.append(f"Error reading file: {e}")

        return results

    async def _process_write_file_tags(self, text: str) -> list[str]:
        """Process [M365_WRITE_FILE] tags."""
        results = []
        pattern = r'\[M365_WRITE_FILE\s+tenant="([^"]+)"\s+site_id="([^"]+)"\s+file_path="([^"]+)"\s+content="([^"]+)"\]'

        for match in re.finditer(pattern, text):
            tenant_name = match.group(1)
            site_id = match.group(2)
            file_path = match.group(3)
            content = match.group(4)

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token for tenant {tenant_name}")
                    continue

                result = await self.sharepoint.write_file(
                    token, site_id, file_path, content
                )
                if result:
                    results.append(
                        f"File written: {file_path} ({result.get('size', 0)} bytes)"
                    )
                else:
                    results.append(f"Failed to write file: {file_path}")
            except Exception as e:
                results.append(f"Error writing file: {e}")

        return results

    async def _process_list_plans_tags(self, text: str) -> list[str]:
        """Process [M365_LIST_PLANS] tags."""
        results = []
        pattern = r'\[M365_LIST_PLANS\s+tenant="([^"]+)"\]'

        for match in re.finditer(pattern, text):
            tenant_name = match.group(1)

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token for tenant {tenant_name}")
                    continue

                plans = await self.planner.list_plans(token)
                if plans:
                    lines = [f"**Planner Plans ({tenant_name}):**"]
                    for plan in plans[:15]:
                        lines.append(f"- {plan['title']} (ID: {plan['id'][:20]}...)")
                    results.append("\n".join(lines))
                else:
                    results.append(f"No plans found for {tenant_name}")
            except Exception as e:
                results.append(f"Error listing plans: {e}")

        return results

    async def _process_list_tasks_tags(self, text: str) -> list[str]:
        """Process [M365_LIST_TASKS] tags."""
        results = []
        pattern = r'\[M365_LIST_TASKS\s+tenant="([^"]+)"\s+plan_id="([^"]+)"(?:\s+bucket_id="([^"]+)")?\]'

        for match in re.finditer(pattern, text):
            tenant_name = match.group(1)
            plan_id = match.group(2)
            bucket_id = match.group(3)

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token for tenant {tenant_name}")
                    continue

                tasks = await self.planner.list_tasks(token, plan_id, bucket_id)
                if tasks:
                    lines = ["**Tasks:**"]
                    for task in tasks[:20]:
                        status = (
                            "done"
                            if task["percent_complete"] == 100
                            else f"{task['percent_complete']}%"
                        )
                        due = (
                            f" (due: {task['due_date'][:10]})"
                            if task.get("due_date")
                            else ""
                        )
                        lines.append(f"- [{status}] {task['title']}{due}")
                    results.append("\n".join(lines))
                else:
                    results.append("No tasks found")
            except Exception as e:
                results.append(f"Error listing tasks: {e}")

        return results

    async def _process_create_task_tags(self, text: str) -> list[str]:
        """Process [M365_CREATE_TASK] tags."""
        results = []
        pattern = r'\[M365_CREATE_TASK\s+tenant="([^"]+)"\s+plan_id="([^"]+)"\s+title="([^"]+)"(?:\s+bucket_id="([^"]+)")?(?:\s+due_date="([^"]+)")?\]'

        for match in re.finditer(pattern, text):
            tenant_name = match.group(1)
            plan_id = match.group(2)
            title = match.group(3)
            bucket_id = match.group(4)
            due_date = match.group(5)

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token for tenant {tenant_name}")
                    continue

                task = await self.planner.create_task(
                    token, plan_id, title, bucket_id, due_date
                )
                if task:
                    results.append(f"Task created: {task['title']} (ID: {task['id']})")
                else:
                    results.append(f"Failed to create task: {title}")
            except Exception as e:
                results.append(f"Error creating task: {e}")

        return results

    async def _process_complete_task_tags(self, text: str) -> list[str]:
        """Process [M365_COMPLETE_TASK] tags."""
        results = []
        pattern = r'\[M365_COMPLETE_TASK\s+tenant="([^"]+)"\s+task_id="([^"]+)"\]'

        for match in re.finditer(pattern, text):
            tenant_name = match.group(1)
            task_id = match.group(2)

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token for tenant {tenant_name}")
                    continue

                success = await self.planner.complete_task(token, task_id)
                if success:
                    results.append(f"Task {task_id} marked as complete")
                else:
                    results.append(f"Failed to complete task {task_id}")
            except Exception as e:
                results.append(f"Error completing task: {e}")

        return results

    async def _process_drive_tags(self, text: str) -> list[str]:
        """Process OneDrive tags."""
        results = []

        # List files
        pattern = (
            r'\[M365_LIST_DRIVE_FILES\s+tenant="([^"]+)"(?:\s+folder_path="([^"]*)")?\]'
        )
        for match in re.finditer(pattern, text):
            tenant_name = match.group(1)
            folder_path = match.group(2) or ""

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token for tenant {tenant_name}")
                    continue

                files = await self.onedrive.list_files(token, folder_path)
                if files:
                    lines = [f"**OneDrive Files ({folder_path or '/'}):**"]
                    for f in files[:20]:
                        icon = "folder" if f["type"] == "folder" else "file"
                        size = f"{f['size'] // 1024}KB" if f["type"] == "file" else ""
                        lines.append(f"- [{icon}] {f['name']} {size}")
                    results.append("\n".join(lines))
                else:
                    results.append("No files found in OneDrive")
            except Exception as e:
                results.append(f"Error listing OneDrive: {e}")

        # Read file
        pattern = r'\[M365_READ_DRIVE_FILE\s+tenant="([^"]+)"\s+file_path="([^"]+)"\]'
        for match in re.finditer(pattern, text):
            tenant_name = match.group(1)
            file_path = match.group(2)

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token for tenant {tenant_name}")
                    continue

                content = await self.onedrive.read_file_text(token, file_path)
                if content:
                    if len(content) > 5000:
                        content = content[:5000] + "\n...(truncated)"
                    results.append(
                        f"**OneDrive File: {file_path}**\n```\n{content}\n```"
                    )
                else:
                    results.append(f"Could not read: {file_path}")
            except Exception as e:
                results.append(f"Error reading OneDrive file: {e}")

        # Write file
        pattern = r'\[M365_WRITE_DRIVE_FILE\s+tenant="([^"]+)"\s+file_path="([^"]+)"\s+content="([^"]+)"\]'
        for match in re.finditer(pattern, text):
            tenant_name = match.group(1)
            file_path = match.group(2)
            content = match.group(3)

            try:
                token = await self._get_token_for_tenant(tenant_name)
                if not token:
                    results.append(f"No token for tenant {tenant_name}")
                    continue

                result = await self.onedrive.write_file(token, file_path, content)
                if result:
                    results.append(f"OneDrive file written: {file_path}")
                else:
                    results.append(f"Failed to write: {file_path}")
            except Exception as e:
                results.append(f"Error writing to OneDrive: {e}")

        return results

    # ========== Public API ==========

    def get_authorization_url(self, state: str | None = None) -> str:
        """Get OAuth authorization URL for user consent.

        Args:
            state: Optional state for CSRF protection

        Returns:
            Authorization URL
        """
        if not self.oauth_manager:
            raise RuntimeError("Plugin not initialized")
        return self.oauth_manager.get_authorization_url(state=state)

    async def handle_oauth_callback(
        self,
        code: str,
        tenant_name: str,
        role: str = "guest",
    ) -> dict[str, Any]:
        """Handle OAuth callback.

        Args:
            code: Authorization code
            tenant_name: Friendly tenant name
            role: User role (owner/guest)

        Returns:
            Token info dict
        """
        if not self.oauth_manager:
            raise RuntimeError("Plugin not initialized")
        return await self.oauth_manager.handle_callback(code, tenant_name, role)

    async def discover_capabilities(self, tenant_name: str) -> dict[str, Any]:
        """Discover capabilities for a tenant.

        Args:
            tenant_name: Tenant name

        Returns:
            Capabilities dict
        """
        if not self.token_store or not self.oauth_manager or not self.graph_client:
            raise RuntimeError("Plugin not initialized")

        tenants = self.token_store.get_all_tenants()
        tenant = next(
            (t for t in tenants if t["tenant_name"].lower() == tenant_name.lower()),
            None,
        )

        if not tenant:
            raise ValueError(f"Tenant not found: {tenant_name}")

        token = await self.oauth_manager.get_valid_token(tenant["tenant_id"])
        if not token:
            raise ValueError(f"No valid token for tenant: {tenant_name}")

        capabilities = await self.graph_client.discover_capabilities(token)

        # Store capabilities
        self.token_store.update_capabilities(tenant["tenant_id"], capabilities)

        return capabilities
