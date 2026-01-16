from PIL import Image
import base64
import json
from pathlib import Path
from typing import Dict, Optional


def parse_tavern_card(filepath: Path) -> dict:
    """
    Extract character data from PNG TavernCard.

    Returns:
        {
            "name": str,
            "description": str,
            "personality": str,
            "scenario": str,
            "first_mes": str,
            "alternate_greetings": [str, ...],
            "example_dialogue": str,
            "tags": [str, ...]
        }
    """
    img = Image.open(filepath)

    metadata = img.info

    chara_data = metadata.get('chara') or metadata.get('ccv3')
    if not chara_data:
        raise ValueError(f"No character data in {filepath}")

    json_str = base64.b64decode(chara_data).decode('utf-8')
    data = json.loads(json_str)

    if 'data' in data:
        data = data['data']

    return {
        "name": data.get("name", "Unknown"),
        "description": data.get("description", ""),
        "personality": data.get("personality", ""),
        "scenario": data.get("scenario", ""),
        "first_mes": data.get("first_mes", ""),
        "alternate_greetings": data.get("alternate_greetings", []),
        "example_dialogue": data.get("mes_example", ""),
        "tags": data.get("tags", [])
    }


def get_all_characters(characters_dir: Path) -> Dict[str, dict]:
    """Load all characters from directory."""
    characters = {}
    for png_file in characters_dir.glob("*.png"):
        try:
            char_id = png_file.stem  
            characters[char_id] = parse_tavern_card(png_file)
            characters[char_id]["id"] = char_id
            characters[char_id]["image_url"] = f"/content/characters/{png_file.name}"
        except Exception as e:
            print(f"Failed to parse {png_file}: {e}")
    return characters


def get_character(characters_dir: Path, char_id: str) -> Optional[dict]:
    """Get single character by ID."""
    png_file = characters_dir / f"{char_id}.png"
    if not png_file.exists():
        return None

    try:
        char = parse_tavern_card(png_file)
        char["id"] = char_id
        char["image_url"] = f"/content/characters/{png_file.name}"
        return char
    except Exception as e:
        print(f"Failed to parse {png_file}: {e}")
        return None
