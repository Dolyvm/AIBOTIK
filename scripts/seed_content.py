
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from shared.models import Character, World
from shared.database import get_session


async def load_characters(session, content_dir: Path):
    characters_dir = content_dir / "characters"
    
    if not characters_dir.exists():
        return
    
    for json_file in characters_dir.glob("*.json"):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        char_id = data.get("id") or json_file.stem
        
        existing = await session.execute(
            select(Character).where(Character.id == char_id)
        )
        if existing.scalar_one_or_none():
            continue
        scenarios = []
        if data.get("first_mes"):
            scenarios.append({
                "index": 0,
                "intro": data["first_mes"],
                "scenario": data.get("scenario", "")
            })
        for i, greeting in enumerate(data.get("alternate_greetings", []), 1):
            scenarios.append({
                "index": i,
                "intro": greeting,
                "scenario": data.get("scenario", "")
            })
        visual_data = {
            "model_type": data.get("model_type", "real"),
            "appearance": data.get("appearance", ""),
            "avatar": data.get("avatar", ""),
            "example_dialogue": data.get("example_dialogue", ""),
            **data.get("visual", {})
        }
        character = Character(
            id=char_id,
            is_public=data.get("is_public", True),
            name=data["name"],
            description=data.get("description", ""),
            personality=data.get("personality", ""),
            visual_data=visual_data,
            scenarios=scenarios,
            tags=data.get("tags", []),
            is_nsfw="NSFW" in data.get("tags", [])
        )
        session.add(character)
    await session.commit()


async def load_worlds(session, content_dir: Path):
    worlds_dir = content_dir / "worlds"
    if not worlds_dir.exists():
        return
    for json_file in worlds_dir.glob("*.json"):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        world_id = data.get("id") or json_file.stem
        existing = await session.execute(
            select(World).where(World.id == world_id)
        )
        if existing.scalar_one_or_none():
            continue
        scenarios = []
        if data.get("intro_message"):
            scenarios.append({
                "index": 0,
                "intro": data["intro_message"],
                "gm_instructions": data.get("gm_instructions", "")
            })
        for i, alt in enumerate(data.get("alternate_scenarios", []), 1):
            scenarios.append({
                "index": i,
                "title": alt.get("title", f"Сценарий {i}"),
                "intro": alt.get("intro", ""),
                "gm_instructions": alt.get("gm_instructions", "")
            })
        locations = []
        if data.get("setting"):
            locations.append({
                "setting": data["setting"]
            })
        world = World(
            id=world_id,
            name=data["name"],
            description=data.get("description", ""),
            cover_image=data.get("cover_image", ""),
            scenarios=scenarios,
            locations=locations,
            tags=data.get("tags", []),
            is_nsfw="NSFW" in data.get("tags", [])
        )
        session.add(world)
    await session.commit()


async def main():
    if Path("/app/content").exists():
        content_dir = Path("/app/content")
    else:
        content_dir = Path(__file__).parent.parent / "content"
    async with get_session() as session:
        await load_characters(session, content_dir)
        await load_worlds(session, content_dir)


if __name__ == "__main__":
    asyncio.run(main())
