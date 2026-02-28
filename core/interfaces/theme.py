"""Base Theme Interface.

Defines the abstract interface for theme plugins that customize the admin UI.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.plugin_manager import PluginManager


class BaseTheme(ABC):
    """Abstract interface for theme plugins.

    Theme plugins provide CSS variables, custom styles, Tailwind config
    overrides, and optional template overrides for the admin UI.
    """

    name: str = ""

    def __init__(self, config: dict):
        self.config = config
        self._plugin_manager: "PluginManager | None" = None

    def set_plugin_manager(self, manager: "PluginManager") -> None:
        self._plugin_manager = manager

    @abstractmethod
    def get_css_variables(self) -> dict[str, dict[str, str]]:
        """Return CSS custom properties for light and dark modes.

        Returns:
            Dict with "light" and "dark" keys, each mapping
            CSS variable names to values.
            Example: {"light": {"--accent": "#14b8a6"}, "dark": {"--accent": "#2dd4bf"}}
        """

    @abstractmethod
    def get_tailwind_config(self) -> dict[str, Any]:
        """Return Tailwind config overrides to merge into the inline config.

        Returns:
            Dict structure matching tailwind.config.theme.extend format.
        """

    @abstractmethod
    def get_custom_css(self) -> str:
        """Return additional CSS to inject (glass effects, animations, etc).

        Returns:
            CSS string to include in a <style> tag.
        """

    def get_static_dir(self) -> Path | None:
        """Return path to theme static assets (logos, fonts, images).

        Returns:
            Path to static directory or None if no static assets.
        """
        return None

    def get_template_overrides(self) -> dict[str, str]:
        """Return template path overrides.

        Keys are the default template paths, values are paths within the
        theme's templates/ directory that should replace them.

        Returns:
            Mapping of original template path to override path.
            Example: {"auth/login.html": "auth/login.html"}
        """
        return {}

    def get_templates_dir(self) -> Path | None:
        """Return path to theme template overrides directory.

        Returns:
            Path to templates directory or None.
        """
        return None

    @abstractmethod
    def get_metadata(self) -> dict[str, str]:
        """Return theme metadata for the admin settings UI.

        Returns:
            Dict with keys: display_name, description, author,
            preview_image (relative to static dir), accent_color.
        """

    async def initialize(self) -> None:
        """Optional setup hook called after loading."""

    async def shutdown(self) -> None:
        """Optional cleanup hook called on shutdown."""
