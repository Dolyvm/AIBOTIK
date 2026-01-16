import httpx
import json
import asyncio
import logging
import random
from pathlib import Path
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential
import fal_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_url(url: str) -> str:
    """
    Remove invisible Unicode characters and whitespace from URL.

    This fixes issues with URLs that contain zero-width spaces,
    invisible separators, or other hidden characters that cause
    HTTP requests to fail.

    Args:
        url: Raw URL string that may contain invisible characters

    Returns:
        Cleaned URL with only visible ASCII and standard URL characters
    """
    if not isinstance(url, str):
        return url

    # Remove all invisible Unicode characters (zero-width, formatting marks, etc.)
    # Keep only printable ASCII and common URL characters
    cleaned = ''.join(char for char in url if char.isprintable())

    # Strip whitespace from both ends
    cleaned = cleaned.strip()

    # Log if invisible characters were found
    if cleaned != url:
        logger.warning(f"Cleaned invisible characters from URL. Original length: {len(url)}, Cleaned length: {len(cleaned)}")
        logger.debug(f"Original URL repr: {repr(url)}")
        logger.debug(f"Cleaned URL: {cleaned}")

    return cleaned

class ImageGenerator:
    def __init__(self, api_key: str, fal_key: Optional[str] = None):
        self.api_key = api_key  # ModelsLab API key
        self.fal_key = fal_key  # Fal.ai API key
        self.text2img_url = "https://modelslab.com/api/v6/images/text2img"

        # Configure fal_client if key provided
        if self.fal_key:
            fal_client.api_key = self.fal_key

        # ModelsLab models
        self.models = {
            "real": "flux-2-dev",  # ModelsLab fallback for real
            "anime": "prefect-illustrious-xl-v1.5"  # ModelsLab for anime
        }
        self.schedulers = {
            "real": "UniPCMultistepScheduler",
            "anime": "UniPCMultistepScheduler"
        }
        self.resolutions = {
            "real": {"width": 1024, "height": 1536},
            "anime": {"width": 1024, "height": 1024}
        }

        # Load meta
        meta_path = Path("/app/content/character_meta.json")
        try:
            with open(meta_path) as f:
                self.character_meta = json.load(f)
            logger.info(f"Loaded characters: {list(self.character_meta.keys())}")
        except Exception as e:
            logger.error(f"Failed to load character meta: {e}")
            self.character_meta = {}

    def _build_prompt(self, meta: dict, custom_prompt: Optional[str] = None) -> str:
        """Build final prompt"""
        base_prompt = custom_prompt or meta.get("visual_prompt", "")
        model_type = meta.get("model_type", "real")

        if model_type == "anime":
            quality = "masterpiece, best quality, highres, detailed"
        else:
            quality = "professional photo, high quality, sharp focus, detailed, RAW photo"

        return f"{quality}, {base_prompt}"

    def _build_negative_prompt(self, meta: dict) -> str:
        """
        Build negative prompt.

        If using modular system, uses generated negative from Prompt.build_prompt().
        Otherwise, falls back to legacy behavior.
        """
        # Check if modular system generated a negative prompt
        if "_generated_negative" in meta:
            generated = meta["_generated_negative"]
            model_type = meta.get("model_type", "real")

            # Add common quality negatives
            common = "child, loli, bad anatomy, deformed, blur, watermark, text, ugly, disfigured, low quality, blurry"

            # Add style-specific negatives
            if model_type == "anime":
                style = "realistic, photo, 3d render"
            else:
                style = "cartoon, anime, drawing, painting, illustration, cgi, 3d, artificial"

            return f"{generated}, {common}, {style}"

        # Legacy behavior
        base_negative = meta.get("negative_prompt", "")
        model_type = meta.get("model_type", "real")

        common = "child, loli, bad anatomy, deformed, blur, watermark, text, ugly, disfigured, low quality, blurry"

        if model_type == "anime":
            style = "realistic, photo, 3d render"
        else:
            style = "cartoon, anime, drawing, painting, illustration, cgi, 3d, artificial"

        return f"{base_negative}, {common}, {style}"

    def _arousal_to_nsfw_level(self, arousal: int, meta: dict) -> str:
        """
        Map arousal (0-100) to NSFW tier name.

        Args:
            arousal: Arousal level from 0 to 100
            meta: Character metadata with nsfw_config

        Returns:
            NSFW tier name: neutral, light, erotic, nudity, explicit, or extreme

        Mapping:
        - 0-16: neutral
        - 17-33: light
        - 34-50: erotic
        - 51-66: nudity
        - 67-83: explicit
        - 84-100: extreme
        """
        nsfw_config = meta.get("nsfw_config", {})
        nsfw_enabled = nsfw_config.get("enabled", True)

        if not nsfw_enabled:
            return "neutral"

        if arousal <= 16:
            return "neutral"
        elif arousal <= 33:
            return "light"
        elif arousal <= 50:
            return "erotic"
        elif arousal <= 66:
            return "nudity"
        elif arousal <= 83:
            return "explicit"
        else:
            return "extreme"

    def _select_prompt_components(self, meta: dict) -> dict:
        """
        Randomly select one component from each category.

        Args:
            meta: Character metadata with prompt_components

        Returns:
            Dict with keys matching Prompt class fields
        """
        components = meta.get("prompt_components", {})

        # Helper to safely get random choice or empty string
        def get_random(items):
            if not items:
                return ""
            if isinstance(items, list) and len(items) > 0:
                return random.choice(items)
            return items if isinstance(items, str) else ""

        return {
            "signature": components.get("signature", ""),
            "body_state": get_random(components.get("body_states", [])),
            "facial_expression": get_random(components.get("facial_expressions", [])),
            "clothing": get_random(components.get("clothing", [])),
            "environment": get_random(components.get("environments", [])),
            "action": get_random(components.get("actions", [])),
            "camera": get_random(components.get("cameras", [])),
            "style": get_random(components.get("styles", []))
        }

    def _build_nsfw_level(self, meta: dict, level_name: str):
        """
        Build NSFWLevel PromptLayer from character metadata.

        Args:
            meta: Character metadata with nsfw_config
            level_name: Tier name (neutral, light, erotic, etc.)

        Returns:
            PromptLayer with tier-specific prompts
        """
        from shared.prompt_assembly import PromptLayer, build_nsfw_layer_from_config

        nsfw_config = meta.get("nsfw_config", {})
        return build_nsfw_layer_from_config(nsfw_config, level_name)

    async def generate(
        self,
        character_id: str,
        scenario_index: int = 0,
        arousal: int = 0,
        prompt_override: Optional[str] = None
    ) -> str:
        """
        Main generation method with modular prompt system.

        Args:
            character_id: Character identifier
            scenario_index: DEPRECATED - kept for backward compatibility, ignored
            arousal: Arousal level 0-100 (maps to NSFW tier)
            prompt_override: Optional custom prompt (bypasses modular system)

        Returns:
            Image URL
        """
        logger.info(f"=== Generating image for: {character_id} ===")
        logger.info(f"Arousal: {arousal}")
        if scenario_index != 0:
            logger.warning(f"scenario_index={scenario_index} is deprecated and will be ignored")

        meta = self.character_meta.get(character_id)
        if not meta:
            raise ValueError(f"Character '{character_id}' not found. Available: {list(self.character_meta.keys())}")

        # If override provided, use legacy path
        if prompt_override:
            logger.info("Using prompt override (legacy mode)")
            scene_prompt = prompt_override
            negative_override = None
        else:
            # NEW: Use modular prompt system
            from shared.prompt_assembly import Prompt

            # Select random components
            components = self._select_prompt_components(meta)
            logger.info(f"Selected components: body_state={components.get('body_state', 'N/A')[:30]}, "
                       f"clothing={components.get('clothing', 'N/A')[:30]}")

            # Map arousal to NSFW tier
            nsfw_tier = self._arousal_to_nsfw_level(arousal, meta)
            logger.info(f"NSFW tier: {nsfw_tier}")

            # Build NSFW level from character config
            nsfw_level = self._build_nsfw_level(meta, nsfw_tier)

            # Build Prompt object
            prompt_obj = Prompt(
                character_base=meta.get("visual_prompt", ""),
                model_type=meta.get("model_type", "real"),
                nsfw_level=nsfw_level,
                **components
            )

            # Generate prompt strings
            scene_prompt, negative_override = prompt_obj.build_prompt()

            # Store negative_override for use in _build_negative_prompt
            meta["_generated_negative"] = negative_override

        logger.info(f"Scene prompt: {scene_prompt[:200]}...")

        # Choose engine based on model_type
        model_type = meta.get("model_type", "real")

        if model_type == "real" and self.fal_key:
            # Use Fal.ai for realistic images
            logger.info("Using Fal.ai engine (Flux)")
            image_url = await self._generate_fal(meta, scene_prompt)
        else:
            # Use ModelsLab for anime or fallback
            logger.info("Using ModelsLab engine")
            image_url = await self._generate_text2img(meta, scene_prompt)

        # Clean up temporary meta
        if "_generated_negative" in meta:
            del meta["_generated_negative"]

        logger.info(f"Image: {image_url}")

        if await self._verify_url(image_url) != 200:
            raise ValueError(f"Image URL invalid: {image_url}")

        return image_url

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _generate_fal(self, meta: dict, prompt: str) -> str:
        """
        Generate image using Fal.ai Flux model.

        Args:
            meta: Character metadata
            prompt: Full prompt including base description and scenario

        Returns:
            Image URL
        """
        if not self.fal_key:
            raise ValueError("Fal.ai API key not configured")

        full_prompt = self._build_prompt(meta, prompt)
        negative_prompt = self._build_negative_prompt(meta)

        logger.info(f"Fal.ai Prompt: {full_prompt[:300]}...")

        # Submit async request to Fal.ai
        def submit_fal():
            handler = fal_client.submit(
                "fal-ai/z-image/turbo",  # Using Z-Image Turbo model
                arguments={
                    "prompt": full_prompt,
                    "enable_safety_checker": False,
                    "image_size": {
                        "width": 1024,
                        "height": 1024
                    }
                }
            )
            return handler

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        handler = await loop.run_in_executor(None, submit_fal)

        # Poll for result
        def get_result():
            return handler.get()

        result = await loop.run_in_executor(None, get_result)

        # Extract image URL from result
        if "images" in result and len(result["images"]) > 0:
            image_data = result["images"][0]
            if isinstance(image_data, dict):
                url = image_data.get("url", "")
            else:
                url = image_data

            # Clean URL from invisible characters
            return clean_url(url)

        raise ValueError(f"No image in Fal.ai response: {result}")

    async def _verify_url(self, url: str) -> int:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.head(url)
                return resp.status_code
            except Exception as e:
                logger.error(f"URL verify failed: {e}")
                return 0

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _generate_text2img(self, meta: dict, prompt: str) -> str:
        """
        Generate image using ModelsLab API.

        Args:
            meta: Character metadata
            prompt: Full prompt including base description and scenario

        Returns:
            Image URL
        """
        model_type = meta.get("model_type", "real")
        model_id = self.models.get(model_type, "flux-2-dev")
        resolution = self.resolutions.get(model_type, {"width": 1024, "height": 1536})
        scheduler = self.schedulers.get(model_type, "UniPCMultistepScheduler")

        full_prompt = self._build_prompt(meta, prompt)
        negative_prompt = self._build_negative_prompt(meta)

        logger.info(f"Model: {model_id}")
        logger.info(f"Prompt: {full_prompt[:300]}...")

        payload = {
            "key": self.api_key,
            "model_id": model_id,
            "prompt": full_prompt,
            "negative_prompt": negative_prompt,
            "width": str(resolution["width"]),
            "height": str(resolution["height"]),
            "samples": "1",
            "num_inference_steps": "40",
            "guidance_scale": 9.0,
            "scheduler": scheduler,
            "safety_checker": "no",
            "enhance_prompt": "no",
            "seed": None
        }

        # Add LoRA if specified in meta
        if "lora_model" in meta:
            payload["lora_model"] = meta["lora_model"]
        if "lora_strength" in meta:
            payload["lora_strength"] = meta["lora_strength"]

        return await self._execute_request(self.text2img_url, payload)

    async def generate_variation(self, character_id: str, variation_name: str) -> str:
        """
        Generate a predefined variation (legacy compatibility).

        Args:
            character_id: Character identifier
            variation_name: Variation name from metadata

        Returns:
            Image URL
        """
        meta = self.character_meta.get(character_id)
        if not meta:
            raise ValueError(f"Character not found: {character_id}")

        variations = meta.get("variations", {})
        variation_prompt = variations.get(variation_name)
        if not variation_prompt:
            raise ValueError(f"Variation '{variation_name}' not found. Available: {list(variations.keys())}")

        return await self.generate(character_id, prompt_override=variation_prompt)

    async def _execute_request(self, url: str, payload: dict) -> str:
        """Execute ModelsLab API request with polling."""
        async with httpx.AsyncClient(timeout=180) as client:
            logger.info(f"POST {url}")
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            logger.info(f"Response status: {data.get('status')}")

            if data.get("status") == "error":
                error_msg = data.get("message") or data.get("messege") or str(data)
                raise ValueError(f"API error: {error_msg}")

            if data.get("status") == "success":
                output = data.get("output", []) or data.get("meta", {}).get("output", [])
                if output:
                    url = output[0]
                    # Clean URL from invisible characters
                    return clean_url(url)
                raise ValueError(f"No output: {data}")

            if data.get("status") == "processing":
                fetch_url = data.get("fetch_result")
                if not fetch_url:
                    raise ValueError("No fetch_result URL")

                for attempt in range(60):
                    delay = min(3 * (1.3 ** (attempt // 5)), 10)
                    await asyncio.sleep(delay)

                    fetch_resp = await client.post(fetch_url, json={"key": self.api_key})
                    fetch_resp.raise_for_status()
                    fetch_data = fetch_resp.json()
                    status = fetch_data.get("status")

                    logger.info(f"Poll {attempt + 1}/60: {status}")

                    if status == "success":
                        output = fetch_data.get("output", []) or fetch_data.get("meta", {}).get("output", [])
                        if output:
                            url = output[0]
                            # Clean URL from invisible characters
                            return clean_url(url)
                        raise ValueError(f"No output: {fetch_data}")
                    elif status == "error":
                        raise ValueError(f"API error: {fetch_data.get('message')}")

                raise TimeoutError("Generation timed out")

            raise ValueError(f"Unexpected response: {data}")
