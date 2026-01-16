"""
Migration script to convert character_meta.json from scenario-based to modular prompt system.

This script:
1. Loads existing character_meta.json
2. For characters with scenarios: extracts components from prompts
3. For characters without scenarios: creates minimal modular structure
4. Writes to character_meta_v2.json for manual review

IMPORTANT: Manual review and refinement required after running this script!
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set


def extract_keywords(text: str, keywords: List[str]) -> Set[str]:
    """Extract matching phrases from text based on keyword list."""
    text_lower = text.lower()
    matches = set()

    for keyword in keywords:
        if keyword in text_lower:
            # Try to extract the full phrase containing the keyword
            # Simple approach: split by commas and find matching parts
            parts = [p.strip() for p in text.split(',')]
            for part in parts:
                if keyword in part.lower():
                    matches.add(part)

    return matches


def extract_components_from_prompts(prompts: List[str]) -> Dict[str, Set[str]]:
    """
    Extract modular components from a list of prompts using keyword matching.

    Returns dict with sets of extracted components for each category.
    """
    # Keyword lists for each component type
    body_keywords = [
        "sitting", "standing", "lying", "kneeling", "leaning", "bent", "crossed",
        "pose", "posing", "arching", "stretching", "reaching", "turning"
    ]

    facial_keywords = [
        "smile", "smiling", "grin", "gaze", "looking", "expression", "eyes",
        "seductive", "flirty", "innocent", "serious", "playful", "sultry",
        "biting lip", "pouty", "wink", "bedroom eyes"
    ]

    clothing_keywords = [
        "dress", "skirt", "blouse", "bikini", "lingerie", "bra", "panties",
        "naked", "nude", "towel", "wearing", "outfit", "attire", "clothes",
        "shirt", "pants", "jeans", "suit", "underwear", "bralette"
    ]

    environment_keywords = [
        "hotel", "room", "bedroom", "bathroom", "car", "gym", "sauna", "pool",
        "bar", "lobby", "locker", "shower", "bed", "couch", "mirror", "window",
        "doorway", "street", "alley", "forest", "beach"
    ]

    action_keywords = [
        "unbuttoning", "adjusting", "holding", "touching", "looking over",
        "biting", "changing", "sitting on", "lying on", "standing by",
        "walking", "posing", "relaxing"
    ]

    camera_keywords = [
        "selfie", "from below", "from above", "mirror", "full body", "close up",
        "angle", "iphone", "instagram", "photo", "shot"
    ]

    style_keywords = [
        "photorealistic", "8k", "raw photo", "natural lighting", "ambient",
        "intimate", "soft lighting", "dim", "bright", "daylight", "steamy",
        "professional", "casual"
    ]

    components = {
        "body_states": set(),
        "facial_expressions": set(),
        "clothing": set(),
        "environments": set(),
        "actions": set(),
        "cameras": set(),
        "styles": set()
    }

    for prompt in prompts:
        components["body_states"].update(extract_keywords(prompt, body_keywords))
        components["facial_expressions"].update(extract_keywords(prompt, facial_keywords))
        components["clothing"].update(extract_keywords(prompt, clothing_keywords))
        components["environments"].update(extract_keywords(prompt, environment_keywords))
        components["actions"].update(extract_keywords(prompt, action_keywords))
        components["cameras"].update(extract_keywords(prompt, camera_keywords))
        components["styles"].update(extract_keywords(prompt, style_keywords))

    return components


def build_nsfw_config_from_scenarios(scenarios: dict, model_type: str) -> dict:
    """
    Build nsfw_config from scenario levels.

    Maps:
    - level_1 → neutral/light tiers
    - level_2 → erotic tier
    - level_3 → explicit/nudity tiers
    """
    nsfw_config = {
        "enabled": True,
        "default_level": "erotic",
        "levels": {}
    }

    # Default NSFW level configurations
    if model_type == "anime":
        nsfw_config["levels"] = {
            "neutral": {
                "prompt": "fully clothed, modest appearance, sfw",
                "negative_prompt": "nudity, sexual content, nsfw, exposed skin"
            },
            "light": {
                "prompt": "suggestive clothing, slight cleavage, cute flirty atmosphere",
                "negative_prompt": "nudity, exposed breasts, explicit content"
            },
            "erotic": {
                "prompt": "revealing outfit, seductive pose, lingerie, intimate atmosphere",
                "negative_prompt": "full nudity, genitals, explicit sexual acts"
            },
            "nudity": {
                "prompt": "topless, exposed breasts, sensual pose, erotic atmosphere",
                "negative_prompt": "genitals visible, explicit sexual penetration"
            },
            "explicit": {
                "prompt": "fully nude, exposed body, erotic pose, sexually suggestive",
                "negative_prompt": "sexual penetration, extreme fetish"
            },
            "extreme": {
                "prompt": "fully nude, explicit erotic pose, sexual content",
                "negative_prompt": "illegal content, violence"
            }
        }
    else:  # real
        nsfw_config["levels"] = {
            "neutral": {
                "prompt": "fully clothed, professional appearance, modest outfit",
                "negative_prompt": "nudity, sexual content, nsfw, exposed skin, lingerie"
            },
            "light": {
                "prompt": "suggestive clothing, subtle cleavage, flirty expression",
                "negative_prompt": "nudity, exposed breasts, explicit content"
            },
            "erotic": {
                "prompt": "revealing lingerie, seductive pose, intimate setting",
                "negative_prompt": "full nudity, genitals visible, explicit sexual acts"
            },
            "nudity": {
                "prompt": "topless, exposed breasts, sensual nude pose",
                "negative_prompt": "genitals visible, sexual penetration"
            },
            "explicit": {
                "prompt": "fully nude, completely exposed body, erotic photography",
                "negative_prompt": "sexual penetration, extreme acts, violence"
            },
            "extreme": {
                "prompt": "fully nude, explicit sexual pose, adult content",
                "negative_prompt": "illegal content, violence, extreme fetish"
            }
        }

    return nsfw_config


def migrate_character(char_id: str, char_data: dict) -> dict:
    """
    Migrate a single character from scenario-based to modular structure.

    Args:
        char_id: Character identifier
        char_data: Original character metadata

    Returns:
        Migrated character metadata with modular components
    """
    print(f"\n{'='*60}")
    print(f"Migrating character: {char_id}")
    print(f"{'='*60}")

    migrated = {
        "model_type": char_data.get("model_type", "real"),
        "visual_prompt": char_data.get("visual_prompt", ""),
        "negative_prompt": char_data.get("negative_prompt", ""),
        "nsfw_tags": char_data.get("nsfw_tags", [])
    }

    # Keep base_prompt if it exists
    if "base_prompt" in char_data:
        migrated["base_prompt"] = char_data["base_prompt"]

    # Keep variations if they exist (for backward compatibility)
    if "variations" in char_data:
        migrated["variations"] = char_data["variations"]
        print(f"  ✓ Kept {len(char_data['variations'])} variations for backward compatibility")

    # Process scenarios if they exist
    if "scenarios" in char_data:
        print(f"  Found {len(char_data['scenarios'])} scenarios")

        # Collect all prompts from all scenarios and levels
        all_prompts = []
        for scenario_key, scenario_data in char_data["scenarios"].items():
            scenario_name = scenario_data.get("name", f"Scenario {scenario_key}")
            print(f"    Processing scenario: {scenario_name}")

            levels = scenario_data.get("levels", {})
            for level_key, level_data in levels.items():
                prompts = level_data.get("prompts", [])
                all_prompts.extend(prompts)
                print(f"      - {level_key}: {len(prompts)} prompts")

        print(f"  Total prompts to analyze: {len(all_prompts)}")

        # Extract components
        components_sets = extract_components_from_prompts(all_prompts)

        # Convert sets to lists and add defaults
        migrated["prompt_components"] = {
            "signature": "",  # Requires manual input
            "body_states": list(components_sets["body_states"]) or [
                "standing confidently",
                "sitting casually",
                "lying down"
            ],
            "facial_expressions": list(components_sets["facial_expressions"]) or [
                "neutral expression",
                "slight smile"
            ],
            "clothing": list(components_sets["clothing"]) or [
                "casual outfit"
            ],
            "environments": list(components_sets["environments"]) or [
                "indoor setting"
            ],
            "actions": list(components_sets["actions"]) or [
                "posing naturally"
            ],
            "cameras": list(components_sets["cameras"]) or [
                "full body shot",
                "from eye level"
            ],
            "styles": list(components_sets["styles"]) or [
                "professional photography"
            ]
        }

        print(f"  Extracted components:")
        for comp_name, comp_list in migrated["prompt_components"].items():
            print(f"    - {comp_name}: {len(comp_list)} items")

        # Build NSFW config
        migrated["nsfw_config"] = build_nsfw_config_from_scenarios(
            char_data["scenarios"],
            migrated["model_type"]
        )
        print(f"  ✓ Created nsfw_config with 6 tiers")

    else:
        # No scenarios - create minimal structure
        print(f"  No scenarios found - creating minimal structure")

        migrated["prompt_components"] = {
            "signature": "",
            "body_states": ["standing", "sitting"],
            "facial_expressions": ["neutral expression", "slight smile"],
            "clothing": ["casual outfit"],
            "environments": ["indoor setting"],
            "actions": ["posing naturally"],
            "cameras": ["full body shot"],
            "styles": ["professional photography"]
        }

        # NSFW disabled for characters without scenarios
        migrated["nsfw_config"] = {
            "enabled": False,
            "default_level": "neutral",
            "levels": {
                "neutral": {
                    "prompt": "fully clothed, modest appearance",
                    "negative_prompt": "nudity, nsfw, sexual content"
                }
            }
        }
        print(f"  ✓ Created minimal structure with nsfw_config.enabled=false")

    return migrated


def migrate_character_meta(input_path: Path, output_path: Path):
    """
    Main migration function.

    Args:
        input_path: Path to original character_meta.json
        output_path: Path to write migrated character_meta_v2.json
    """
    print(f"\n{'#'*60}")
    print(f"# CHARACTER META MIGRATION SCRIPT")
    print(f"{'#'*60}\n")

    print(f"Loading: {input_path}")
    with open(input_path, encoding='utf-8') as f:
        old_meta = json.load(f)

    print(f"Found {len(old_meta)} characters to migrate\n")

    new_meta = {}

    for char_id, char_data in old_meta.items():
        try:
            new_meta[char_id] = migrate_character(char_id, char_data)
        except Exception as e:
            print(f"  ❌ ERROR migrating {char_id}: {e}")
            print(f"  Keeping original data for this character")
            new_meta[char_id] = char_data

    print(f"\n{'='*60}")
    print(f"Writing migrated data to: {output_path}")
    print(f"{'='*60}\n")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(new_meta, f, indent=2, ensure_ascii=False)

    print(f"✅ Migration complete!\n")
    print(f"{'#'*60}")
    print(f"# IMPORTANT: MANUAL REVIEW REQUIRED")
    print(f"{'#'*60}\n")
    print("Next steps:")
    print("1. Review character_meta_v2.json")
    print("2. Add character signatures (prompt_components.signature)")
    print("3. Refine extracted components (remove duplicates/nonsensical entries)")
    print("4. Add character-specific cameras and styles")
    print("5. Adjust NSFW tier prompts if needed")
    print("6. Test generation with each character")
    print(f"\nWhen ready, replace original:")
    print(f"  cp {output_path} {input_path}\n")


if __name__ == "__main__":
    # Paths relative to project root
    base_dir = Path(__file__).parent.parent
    input_file = base_dir / "content" / "character_meta.json"
    output_file = base_dir / "content" / "character_meta_v2.json"

    if not input_file.exists():
        print(f"❌ Error: {input_file} not found!")
        print("Make sure you're running this script from the project root or migrations directory")
        exit(1)

    migrate_character_meta(input_file, output_file)
