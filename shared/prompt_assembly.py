"""
Modular prompt assembly system for AI image generation.

This module provides a flexible component-based approach to building prompts
with NSFW tier support and quality prefixes for different model types.
"""

from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel, field_validator


@dataclass(frozen=True)
class PromptLayer:
    """
    A layer containing prompt additions and negative prompt exclusions.

    Used primarily for NSFW tier configuration.
    """
    prompt: str = ""
    negative_prompt: str = ""


@dataclass
class NSFWLevel:
    """
    NSFW tier configuration with 6 levels mapped to arousal ranges.

    Arousal mapping:
    - neutral (0-16): Fully clothed, modest appearance
    - light (17-33): Suggestive clothing, slight cleavage
    - erotic (34-50): Revealing outfit, seductive pose
    - nudity (51-66): Topless, exposed breasts
    - explicit (67-83): Fully nude, exposed body
    - extreme (84-100): Fully nude, explicit pose
    """
    neutral: PromptLayer = PromptLayer(
        prompt="fully clothed, modest appearance",
        negative_prompt="nudity, sexual content, exposed skin, lingerie"
    )
    light: PromptLayer = PromptLayer(
        prompt="suggestive clothing, subtle cleavage",
        negative_prompt="nudity, explicit content, exposed breasts"
    )
    erotic: PromptLayer = PromptLayer(
        prompt="revealing outfit, seductive pose, intimate atmosphere",
        negative_prompt="full nudity, genitals, explicit sexual acts"
    )
    nudity: PromptLayer = PromptLayer(
        prompt="topless, exposed breasts, sensual pose",
        negative_prompt="genitals visible, explicit sexual acts, penetration"
    )
    explicit: PromptLayer = PromptLayer(
        prompt="fully nude, exposed body, erotic pose",
        negative_prompt="sexual penetration, extreme fetish, violence"
    )
    extreme: PromptLayer = PromptLayer(
        prompt="fully nude, explicit erotic pose, sexually suggestive",
        negative_prompt="illegal content, violence, extreme fetish"
    )


class Prompt(BaseModel):
    """
    Modular prompt builder with component-based construction.

    Components are combined in a logical order to create coherent prompts
    for AI image generation. Supports both anime and realistic model types
    with appropriate quality prefixes.
    """
    # Core character description
    character_base: Optional[str] = ""

    # Optional character signature/catchphrase
    signature: Optional[str] = ""

    # Physical pose and body position
    body_state: Optional[str] = ""

    # Facial emotion and expression
    facial_expression: Optional[str] = ""

    # Clothing and outfit description
    clothing: Optional[str] = ""

    # Setting and location
    environment: Optional[str] = ""

    # Action or movement
    action: Optional[str] = ""

    # Camera angle and framing
    camera: Optional[str] = ""

    # Artistic style and quality modifiers
    style: Optional[str] = ""

    # NSFW tier configuration
    nsfw_level: PromptLayer = NSFWLevel.neutral

    # Model type for quality prefix selection
    model_type: str = "real"

    @field_validator('nsfw_level', mode='before')
    def validate_nsfw_level(cls, v):
        """
        Allow string-based NSFW level input.

        Accepts tier names like "neutral", "erotic", etc. and converts
        them to PromptLayer objects from NSFWLevel.
        """
        if isinstance(v, str):
            level = getattr(NSFWLevel, v, None)
            if level is None:
                # If invalid tier name, default to neutral
                return NSFWLevel.neutral
            return level
        if isinstance(v, PromptLayer):
            return v
        # If dict, construct PromptLayer
        if isinstance(v, dict):
            return PromptLayer(**v)
        return NSFWLevel.neutral

    def build_prompt(self, build_as_type: Optional[str] = None) -> tuple[str, str]:
        """
        Build complete prompt and negative prompt strings.

        Args:
            build_as_type: Override model_type for quality prefix selection.
                          Useful for testing or special cases.

        Returns:
            Tuple of (positive_prompt, negative_prompt)

        The prompt is constructed in this order:
        1. Quality prefix (based on model type)
        2. Character base description
        3. Character signature
        4. Body state
        5. Facial expression
        6. Clothing
        7. Environment
        8. Action
        9. Camera angle
        10. Style modifiers
        11. NSFW tier additions
        """
        prompt_parts = []
        negative_parts = []

        # Determine model type
        active_model_type = build_as_type or self.model_type

        # Add quality prefix based on model type
        if active_model_type == "anime":
            prompt_parts.append("masterpiece, best quality, highres, detailed")
        else:  # real
            prompt_parts.append("professional photo, high quality, sharp focus, detailed, RAW photo")

        # Add all component fields in logical order
        for field_name in [
            "character_base",
            "signature",
            "body_state",
            "facial_expression",
            "clothing",
            "environment",
            "action",
            "camera",
            "style"
        ]:
            value = getattr(self, field_name)
            if value:
                prompt_parts.append(value)

        # Add NSFW tier modifiers
        if self.nsfw_level and self.nsfw_level.prompt:
            prompt_parts.append(self.nsfw_level.prompt)

        if self.nsfw_level and self.nsfw_level.negative_prompt:
            negative_parts.append(self.nsfw_level.negative_prompt)

        # Combine parts into final prompts
        prompt = ", ".join(prompt_parts)
        negative_prompt = ", ".join(negative_parts)

        return prompt, negative_prompt


# Convenience function for creating NSFW levels from character metadata
def build_nsfw_layer_from_config(config: dict, tier_name: str) -> PromptLayer:
    """
    Build a PromptLayer from character NSFW configuration.

    Args:
        config: Character's nsfw_config dict
        tier_name: Name of the tier (neutral, light, erotic, etc.)

    Returns:
        PromptLayer with tier-specific prompts

    Example:
        >>> config = {
        ...     "levels": {
        ...         "erotic": {
        ...             "prompt": "revealing lingerie",
        ...             "negative_prompt": "full nudity"
        ...         }
        ...     }
        ... }
        >>> layer = build_nsfw_layer_from_config(config, "erotic")
        >>> layer.prompt
        'revealing lingerie'
    """
    levels = config.get("levels", {})
    tier_config = levels.get(tier_name, {})

    return PromptLayer(
        prompt=tier_config.get("prompt", ""),
        negative_prompt=tier_config.get("negative_prompt", "")
    )


def map_arousal_to_tier(arousal: int, nsfw_enabled: bool = True) -> str:
    """
    Map arousal level (0-100) to NSFW tier name.

    Args:
        arousal: Arousal level from 0 to 100
        nsfw_enabled: Whether NSFW content is enabled for this character

    Returns:
        Tier name: neutral, light, erotic, nudity, explicit, or extreme

    Mapping:
    - 0-16: neutral
    - 17-33: light
    - 34-50: erotic
    - 51-66: nudity
    - 67-83: explicit
    - 84-100: extreme

    If NSFW is disabled, always returns "neutral" regardless of arousal.
    """
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


if __name__ == "__main__":
    # Example usage
    print("=== Example 1: Anime character with erotic tier ===")
    prompt = Prompt(
        character_base="1girl, purple eyes, long black hair, athletic body",
        signature="playful personality",
        body_state="sitting on bed, legs crossed",
        facial_expression="seductive smile, bedroom eyes",
        clothing="black lace lingerie",
        environment="luxury hotel room, soft lighting",
        action="looking over shoulder at camera",
        camera="from slightly above, intimate angle",
        style="anime style, soft colors, detailed shading",
        nsfw_level="erotic",
        model_type="anime"
    )

    pos, neg = prompt.build_prompt()
    print("Positive prompt:")
    print(pos)
    print("\nNegative prompt:")
    print(neg)

    print("\n=== Example 2: Realistic character with light tier ===")
    prompt2 = Prompt(
        character_base="27 year old blonde woman, slim athletic build, blue eyes",
        body_state="standing confidently, weight on one hip",
        facial_expression="slight smile, direct gaze",
        clothing="white tank top, fitted jeans",
        environment="modern apartment, natural lighting",
        action="adjusting hair",
        camera="full body shot, eye level",
        style="professional photography, sharp focus",
        nsfw_level="light",
        model_type="real"
    )

    pos2, neg2 = prompt2.build_prompt()
    print("Positive prompt:")
    print(pos2)
    print("\nNegative prompt:")
    print(neg2)

    print("\n=== Example 3: Arousal mapping ===")
    for arousal in [0, 20, 40, 60, 75, 95]:
        tier = map_arousal_to_tier(arousal)
        print(f"Arousal {arousal} → {tier}")
