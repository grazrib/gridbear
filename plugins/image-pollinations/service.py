"""Pollinations.ai Image Provider.

Free image generation using Pollinations.ai API.
No API key required.
"""

import asyncio
import uuid
from pathlib import Path
from urllib.parse import quote

import aiohttp

from config.logging_config import logger
from core.interfaces.service import BaseImageService

POLLINATIONS_BASE_URL = "https://image.pollinations.ai/prompt"


class PollinationsImageService(BaseImageService):
    """Image generation service using Pollinations.ai."""

    name = "image-pollinations"

    def __init__(self, config: dict):
        super().__init__(config)
        self.model = config.get("model", "nanobanana-pro")
        self.width = config.get("width", 1024)
        self.height = config.get("height", 1024)
        self.output_dir = Path(config.get("output_dir", "data/images"))

    async def initialize(self) -> None:
        logger.info(f"Pollinations image service initialized (model={self.model})")

    async def shutdown(self) -> None:
        pass

    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
    ) -> str:
        """Generate image from prompt via Pollinations.ai.

        Args:
            prompt: Description of image to generate
            size: Image dimensions (e.g., "1024x1024")

        Returns:
            Path to generated image file or empty string on failure
        """
        if "x" in size:
            try:
                width, height = map(int, size.split("x"))
            except ValueError:
                width, height = self.width, self.height
        else:
            width, height = self.width, self.height

        output_path = self.output_dir / f"gridbear_img_{uuid.uuid4().hex}.jpg"
        encoded_prompt = quote(prompt)
        url = (
            f"{POLLINATIONS_BASE_URL}/{encoded_prompt}"
            f"?model={self.model}&width={width}&height={height}"
        )

        logger.info(f"Pollinations generating image: {prompt[:50]}...")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if response.status == 200:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        content = await response.read()
                        output_path.write_bytes(content)
                        logger.info(f"Image saved to {output_path}")
                        return str(output_path)
                    else:
                        logger.error(f"Pollinations error: HTTP {response.status}")
                        return ""
        except asyncio.TimeoutError:
            logger.error("Pollinations image generation timed out")
            return ""
        except Exception as e:
            logger.error(f"Pollinations error: {e}")
            return ""
