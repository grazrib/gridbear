"""Hook System for GridBear.

Allows plugins to intercept and modify behavior at key points in the message flow.
"""

from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable

from config.logging_config import logger


class HookName(str, Enum):
    """Available hook points.

    Inherits from str so enum values work as dict keys and in string
    comparisons — existing plugins using plain strings still work.
    """

    # Message flow
    ON_MESSAGE_RECEIVED = "on_message_received"
    BEFORE_CONTEXT_BUILD = "before_context_build"
    AFTER_CONTEXT_BUILD = "after_context_build"
    BEFORE_RUNNER_CALL = "before_runner_call"
    AFTER_RUNNER_CALL = "after_runner_call"
    BEFORE_SEND_RESPONSE = "before_send_response"
    # Memory
    BEFORE_MEMORY_STORE = "before_memory_store"
    AFTER_MEMORY_STORE = "after_memory_store"
    # Session
    ON_SESSION_CREATED = "on_session_created"
    ON_SESSION_EXPIRED = "on_session_expired"
    # Lifecycle
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"
    ON_PLUGIN_LOADED = "on_plugin_loaded"


@dataclass
class HookRegistration:
    """A registered hook function."""

    name: str
    function: Callable
    priority: int = 1
    plugin_name: str = ""


class HookManager:
    """Manages hook registration and execution."""

    HOOKS = [h.value for h in HookName]

    def __init__(self):
        self._hooks: dict[str, list[HookRegistration]] = {
            hook: [] for hook in self.HOOKS
        }

    def register(
        self,
        hook_name: str | HookName,
        function: Callable,
        priority: int = 1,
        plugin_name: str = "",
    ) -> None:
        """Register a hook function.

        Args:
            hook_name: Hook point (HookName enum or string)
            function: Function to call
            priority: Higher priority runs first (default: 1)
            plugin_name: Name of the plugin registering this hook
        """
        if hook_name not in self._hooks:
            logger.warning(f"Unknown hook: {hook_name}")
            return

        registration = HookRegistration(
            name=hook_name,
            function=function,
            priority=priority,
            plugin_name=plugin_name,
        )
        self._hooks[hook_name].append(registration)

        # Sort by priority (higher first)
        self._hooks[hook_name].sort(key=lambda h: h.priority, reverse=True)

        logger.debug(
            f"Registered hook: {hook_name} from {plugin_name or 'unknown'} (priority={priority})"
        )

    def unregister(self, hook_name: str, function: Callable) -> None:
        """Unregister a hook function."""
        if hook_name in self._hooks:
            self._hooks[hook_name] = [
                h for h in self._hooks[hook_name] if h.function != function
            ]

    def unregister_plugin(self, plugin_name: str) -> None:
        """Unregister all hooks from a plugin."""
        for hook_name in self._hooks:
            self._hooks[hook_name] = [
                h for h in self._hooks[hook_name] if h.plugin_name != plugin_name
            ]

    async def execute(
        self, hook_name: str | HookName, data: Any = None, **kwargs
    ) -> Any:
        """Execute all registered hooks for a hook point.

        Args:
            hook_name: Hook point (HookName enum or string)
            data: Data to pass through hooks (each hook can modify it)
            **kwargs: Additional context passed to hooks

        Returns:
            Modified data after all hooks have run
        """
        if hook_name not in self._hooks:
            return data

        for registration in self._hooks[hook_name]:
            try:
                result = registration.function(data, **kwargs)
                # Support async hooks
                if hasattr(result, "__await__"):
                    result = await result

                # If hook returns something, use it as new data
                if result is not None:
                    data = result

            except Exception as e:
                logger.error(
                    f"Hook error in {registration.plugin_name}.{hook_name}: {e}"
                )

        return data

    def execute_sync(
        self, hook_name: str | HookName, data: Any = None, **kwargs
    ) -> Any:
        """Execute hooks synchronously (for non-async contexts)."""
        if hook_name not in self._hooks:
            return data

        for registration in self._hooks[hook_name]:
            try:
                result = registration.function(data, **kwargs)
                if result is not None:
                    data = result
            except Exception as e:
                logger.error(
                    f"Hook error in {registration.plugin_name}.{hook_name}: {e}"
                )

        return data

    def list_hooks(self) -> dict[str, list[str]]:
        """List all registered hooks by hook point."""
        return {
            hook_name: [
                f"{h.plugin_name}:{h.function.__name__} (priority={h.priority})"
                for h in hooks
            ]
            for hook_name, hooks in self._hooks.items()
            if hooks
        }


# Global hook manager instance
hook_manager = HookManager()


def hook(hook_name: str | HookName, priority: int = 1):
    """Decorator to register a function as a hook.

    Usage in a plugin:
        from core.hooks import hook, HookName

        @hook(HookName.BEFORE_SEND_RESPONSE, priority=5)
        def modify_response(data, **kwargs):
            data["text"] = data["text"].upper()
            return data

    Plain strings still work for backward compatibility:
        @hook("before_send_response", priority=5)

    Args:
        hook_name: Hook point (HookName enum or string)
        priority: Higher priority runs first (default: 1)
    """

    def decorator(func: Callable) -> Callable:
        # Store hook info on function for later registration
        if not hasattr(func, "_gridbear_hooks"):
            func._gridbear_hooks = []
        func._gridbear_hooks.append(
            {
                "hook_name": hook_name,
                "priority": priority,
            }
        )

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # Copy hook info to wrapper
        wrapper._gridbear_hooks = func._gridbear_hooks
        return wrapper

    return decorator


@dataclass
class HookData:
    """Standard data structure passed to hooks."""

    # Message data
    text: str = ""
    platform: str = ""
    user_id: int = 0
    username: str | None = None
    attachments: list[str] = field(default_factory=list)

    # Context data
    prompt: str = ""
    session_id: str | None = None
    mcp_permissions: list[str] = field(default_factory=list)

    # Response data
    response_text: str = ""

    # Extra data (plugins can add custom fields)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "platform": self.platform,
            "user_id": self.user_id,
            "username": self.username,
            "attachments": self.attachments,
            "prompt": self.prompt,
            "session_id": self.session_id,
            "mcp_permissions": self.mcp_permissions,
            "response_text": self.response_text,
            "extra": self.extra,
        }
