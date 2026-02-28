"""Image Service Base Plugin.

Stub service — the actual generation is delegated to providers
(image-pollinations, image-openai, etc.) via virtual_tools.py.
"""

from config.logging_config import logger
from core.interfaces.service import BaseImageService


class ImageService(BaseImageService):
    """Base image service stub.

    This plugin owns the image__generate MCP tool (via virtual_tools.py)
    and delegates actual generation to the provider configured in the
    agent's YAML (image.provider).
    """

    name = "image"

    async def initialize(self) -> None:
        logger.info("Image base plugin loaded (delegates to providers)")

    async def shutdown(self) -> None:
        pass

    async def generate(self, prompt: str, size: str = "1024x1024") -> str:
        raise NotImplementedError(
            "Use the image__generate virtual tool — this stub is not called directly"
        )
