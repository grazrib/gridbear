"""OpenAI DALL-E Image Provider.

Image generation using OpenAI's DALL-E API.
Requires OPENAI_API_KEY in secrets manager.
"""

import uuid
from pathlib import Path

import aiohttp

from config.logging_config import logger
from core.interfaces.service import BaseImageService

OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"


class OpenAIImageService(BaseImageService):
    """Image generation service using OpenAI DALL-E."""

    name = "image-openai"

    def __init__(self, config: dict):
        super().__init__(config)
        self.model = config.get("model", "dall-e-3")
        self.quality = config.get("quality", "standard")
        self.output_dir = Path(config.get("output_dir", "data/images"))
        self._api_key = None

    async def initialize(self) -> None:
        from ui.secrets_manager import secrets_manager

        self._api_key = secrets_manager.get_plain("OPENAI_API_KEY")
        if not self._api_key:
            logger.warning("OpenAI image service: OPENAI_API_KEY not found")
        else:
            logger.info(f"OpenAI image service initialized (model={self.model})")

    async def shutdown(self) -> None:
        pass

    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
    ) -> str:
        """Generate image from prompt via OpenAI DALL-E.

        Args:
            prompt: Description of image to generate
            size: Image dimensions (e.g., "1024x1024")

        Returns:
            Path to generated image file or empty string on failure
        """
        if not self._api_key:
            logger.error("OpenAI image: no API key configured")
            return ""

        # Validate size for dall-e-3
        valid_sizes = {"1024x1024", "1792x1024", "1024x1792"}
        if size not in valid_sizes:
            size = "1024x1024"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": size,
        }
        if self.model == "dall-e-3":
            payload["quality"] = self.quality

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        logger.info(f"DALL-E generating image: {prompt[:50]}...")

        try:
            async with aiohttp.ClientSession() as session:
                # Request image generation
                async with session.post(
                    OPENAI_IMAGES_URL,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        logger.error(
                            f"DALL-E API error: HTTP {response.status}: {body[:200]}"
                        )
                        return ""
                    data = await response.json()

                image_url = data["data"][0]["url"]

                # Download the generated image
                async with session.get(
                    image_url,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as img_response:
                    if img_response.status != 200:
                        logger.error(
                            f"Failed to download DALL-E image: HTTP {img_response.status}"
                        )
                        return ""
                    content = await img_response.read()

            output_path = self.output_dir / f"gridbear_img_{uuid.uuid4().hex}.png"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)
            logger.info(f"DALL-E image saved to {output_path}")
            return str(output_path)

        except Exception as e:
            logger.error(f"DALL-E error: {e}")
            return ""
