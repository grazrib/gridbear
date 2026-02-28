"""Base Runner Interface.

Defines the abstract interface for AI backend runners (Claude, Ollama, etc).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RunnerResponse:
    """Response from an AI runner."""

    text: str
    session_id: str | None = None
    cost_usd: float = 0.0
    is_error: bool = False
    raw: dict = field(default_factory=dict)


class BaseRunner(ABC):
    """Abstract interface for AI backend runners."""

    name: str = ""

    def __init__(self, config: dict):
        """Initialize runner with configuration.

        Args:
            config: Plugin configuration dict
        """
        self.config = config

    @abstractmethod
    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
        **kwargs,
    ) -> RunnerResponse:
        """Execute prompt and return response.

        Args:
            prompt: The prompt to send to the AI
            session_id: Optional session identifier for context
            **kwargs: Additional runner-specific arguments

        Returns:
            RunnerResponse with the AI's response
        """
        pass

    @abstractmethod
    async def supports_tools(self) -> bool:
        """Check if runner supports MCP/tools."""
        pass

    @abstractmethod
    async def supports_vision(self) -> bool:
        """Check if runner supports image input."""
        pass

    async def initialize(self) -> None:
        """Optional initialization setup."""
        pass

    async def shutdown(self) -> None:
        """Optional cleanup on shutdown."""
        pass

    @property
    def available_models(self) -> list[tuple[str, str]]:
        """Return available model choices as (value, label) tuples.

        Override in subclass to provide runner-specific models.
        First element is used as the CLI --model value, second as display label.
        """
        return []
