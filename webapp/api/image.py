"""
Image generation API endpoints.

Provides endpoints for building prompts and generating images using the modular prompt system.
"""

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Optional
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.services.imagegen import ImageGenerator

router = APIRouter(prefix="/api/image", tags=["image"])

# Initialize ImageGenerator
MODELSLAB_API_KEY = os.getenv("MODELSLAB_API_KEY", "")
FAL_KEY = os.getenv("FAL_KEY", "")
image_generator = ImageGenerator(api_key=MODELSLAB_API_KEY, fal_key=FAL_KEY)


class BuildPromptRequest(BaseModel):
    """Request model for building a prompt without generating an image."""
    character_id: str
    arousal: int = 0


class BuildPromptResponse(BaseModel):
    """Response model containing built prompt and metadata."""
    prompt: str
    negative_prompt: str
    nsfw_level: str
    components: dict


class GenerateImageRequest(BaseModel):
    """Request model for image generation."""
    character_id: str
    arousal: int = 0
    prompt_override: Optional[str] = None


class GenerateImageResponse(BaseModel):
    """Response model for image generation."""
    success: bool
    image_url: str


@router.post("/build_prompt", response_model=BuildPromptResponse)
async def build_prompt(req: BuildPromptRequest = Body(...)):
    """
    Build a prompt using the modular system without generating an image.

    This endpoint is useful for:
    - Preview/debugging prompt construction
    - Testing different arousal levels
    - Understanding component selection

    Args:
        req: BuildPromptRequest with character_id and arousal level

    Returns:
        BuildPromptResponse with prompt, negative_prompt, nsfw_level, and selected components

    Raises:
        HTTPException 404: Character not found
        HTTPException 500: Error building prompt
    """
    try:
        meta = image_generator.character_meta.get(req.character_id)
        if not meta:
            raise HTTPException(
                status_code=404,
                detail=f"Character '{req.character_id}' not found. "
                      f"Available: {list(image_generator.character_meta.keys())}"
            )

        # Select random components
        components = image_generator._select_prompt_components(meta)

        # Determine NSFW level
        nsfw_tier = image_generator._arousal_to_nsfw_level(req.arousal, meta)

        # Build NSFW level from character config
        nsfw_level = image_generator._build_nsfw_level(meta, nsfw_tier)

        # Build prompt object
        from shared.prompt_assembly import Prompt

        prompt_obj = Prompt(
            character_base=meta.get("visual_prompt", ""),
            model_type=meta.get("model_type", "real"),
            nsfw_level=nsfw_level,
            **components
        )

        # Generate prompt strings
        prompt_str, negative_str = prompt_obj.build_prompt()

        return BuildPromptResponse(
            prompt=prompt_str,
            negative_prompt=negative_str,
            nsfw_level=nsfw_tier,
            components=components
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error building prompt: {str(e)}"
        )


@router.post("/generate", response_model=GenerateImageResponse)
async def generate_image(req: GenerateImageRequest = Body(...)):
    """
    Generate image using modular prompt system.

    This endpoint generates images without charging tokens (internal API).
    For user-facing generation with token costs, use /api/chat/{chat_id}/photo

    Args:
        req: GenerateImageRequest with character_id, arousal, and optional prompt_override

    Returns:
        GenerateImageResponse with success status and image_url

    Raises:
        HTTPException 404: Character not found
        HTTPException 500: Image generation failed
    """
    try:
        image_url = await image_generator.generate(
            character_id=req.character_id,
            arousal=req.arousal,
            prompt_override=req.prompt_override
        )

        return GenerateImageResponse(
            success=True,
            image_url=image_url
        )

    except ValueError as e:
        # Character not found or invalid URL
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Image generation failed: {str(e)}"
        )


@router.get("/characters")
async def list_characters():
    """
    List all available characters with their metadata.

    Returns:
        Dict with character IDs as keys and basic metadata as values
    """
    characters = {}

    for char_id, meta in image_generator.character_meta.items():
        characters[char_id] = {
            "id": char_id,
            "model_type": meta.get("model_type", "real"),
            "nsfw_enabled": meta.get("nsfw_config", {}).get("enabled", False),
            "has_scenarios": "scenarios" in meta,  # Legacy
            "has_variations": "variations" in meta,
            "has_modular_components": "prompt_components" in meta
        }

    return characters


@router.get("/characters/{character_id}/components")
async def get_character_components(character_id: str):
    """
    Get modular components for a specific character.

    Useful for understanding what components are available for this character.

    Args:
        character_id: Character identifier

    Returns:
        Character's prompt_components dict

    Raises:
        HTTPException 404: Character not found
    """
    meta = image_generator.character_meta.get(character_id)
    if not meta:
        raise HTTPException(
            status_code=404,
            detail=f"Character '{character_id}' not found"
        )

    components = meta.get("prompt_components", {})
    if not components:
        raise HTTPException(
            status_code=404,
            detail=f"Character '{character_id}' has no modular components configured"
        )

    return {
        "character_id": character_id,
        "model_type": meta.get("model_type", "real"),
        "components": components,
        "nsfw_config": meta.get("nsfw_config", {})
    }
