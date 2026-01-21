#!/usr/bin/env python3
"""
scripts/seed_content.py - Загрузка персонажей и миров из JSON в PostgreSQL

ЭТОТ ФАЙЛ ОТСУТСТВУЕТ В РЕПОЗИТОРИИ И НЕОБХОДИМ ДЛЯ РАБОТЫ!
"""
import asyncio
import json
import sys
from pathlib import Path

# Добавляем путь к shared модулю
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import os

# Импорты из shared
from shared.models import Base, Character, World
from shared.config import DATABASE_URL


async def load_characters(session: AsyncSession, content_dir: Path):
    """Загрузка персонажей из JSON файлов"""
    characters_dir = content_dir / "characters"
    
    if not characters_dir.exists():
        print(f"⚠️  Директория {characters_dir} не найдена")
        return
    
    for json_file in characters_dir.glob("*.json"):
        print(f"📁 Обработка: {json_file.name}")
        
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        char_id = data.get("id") or json_file.stem
        
        # Проверяем существование
        existing = await session.execute(
            select(Character).where(Character.id == char_id)
        )
        if existing.scalar_one_or_none():
            print(f"  ⏭️  Персонаж '{char_id}' уже существует, пропускаем")
            continue
        
        # Формируем scenarios из first_mes и alternate_greetings
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
        
        # Формируем visual_data
        visual_data = {
            "model_type": data.get("model_type", "real"),
            "appearance": data.get("appearance", ""),
            "avatar": data.get("avatar", ""),
            "example_dialogue": data.get("example_dialogue", ""),
            **data.get("visual", {})
        }
        
        character = Character(
            id=char_id,
            name=data["name"],
            description=data.get("description", ""),
            personality=data.get("personality", ""),
            visual_data=visual_data,
            scenarios=scenarios,
            tags=data.get("tags", []),
            is_nsfw="NSFW" in data.get("tags", [])
        )
        
        session.add(character)
        print(f"  ✅ Добавлен персонаж: {data['name']}")
    
    await session.commit()


async def load_worlds(session: AsyncSession, content_dir: Path):
    """Загрузка миров из JSON файлов"""
    worlds_dir = content_dir / "worlds"
    
    if not worlds_dir.exists():
        print(f"⚠️  Директория {worlds_dir} не найдена")
        return
    
    for json_file in worlds_dir.glob("*.json"):
        print(f"📁 Обработка: {json_file.name}")
        
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        world_id = data.get("id") or json_file.stem
        
        # Проверяем существование
        existing = await session.execute(
            select(World).where(World.id == world_id)
        )
        if existing.scalar_one_or_none():
            print(f"  ⏭️  Мир '{world_id}' уже существует, пропускаем")
            continue
        
        # Формируем scenarios
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
        
        # Формируем locations
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
        print(f"  ✅ Добавлен мир: {data['name']}")
    
    await session.commit()


async def main():
    """Основная функция seed"""
    print("=" * 60)
    print("🌱 Seed Content Script")
    print("=" * 60)
    
    # Определяем путь к контенту
    # В Docker: /app/content
    # Локально: ./content
    if Path("/app/content").exists():
        content_dir = Path("/app/content")
    else:
        content_dir = Path(__file__).parent.parent / "content"
    
    print(f"📂 Директория контента: {content_dir}")
    
    # Подключение к БД
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        print("\n📚 Загрузка персонажей...")
        await load_characters(session, content_dir)
        
        print("\n🌍 Загрузка миров...")
        await load_worlds(session, content_dir)
    
    await engine.dispose()
    
    print("\n" + "=" * 60)
    print("✅ Seed завершён успешно!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
