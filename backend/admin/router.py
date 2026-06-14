from fastapi import APIRouter, Request, HTTPException, Depends, Form, Header, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging
import json
import re

from datetime import datetime
from shared.models import Prompt, User, Character, World, Chat, get_async_session
from shared.config import ADMIN_TELEGRAM_IDS, BOT_TOKEN
from shared.services.prompt_service import reload_cache, DEFAULT_PROMPTS, create_or_update_character_modifiers, \
    get_character_modifiers_from_db
from shared.constants import invalidate_character_modifiers_cache
from shared.services.cache import get_cache
from shared.services.image_storage import (
    get_public_url,
    save_world_cover,
)
from shared.services.image_cleanup import collect_character_file_paths, delete_files
from shared.services.model_types import validate_model_gender
from telegram_init_data import validate, parse

from shared.services.statistics import StatisticsService
from shared.services.subscription import get_subscription_service
from shared.models import SubscriptionPlan
from shared.subscription_plans import USAGE_TYPE_MAP
from shared.database.repositories.subscription import SubscriptionRepository
from datetime import datetime as _dt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="admin/templates")

PROMPT_CATEGORIES = {
    "settings": "Settings",
    "character": "Character Prompts",
    "player": "Player Prompts",
    "summary": "Summary Prompts",
    "creation": "Character Creation",
    "modifiers": "Character Modifiers",
}

HIDDEN_PROMPT_KEYS = {"llm_active_model"}


async def get_current_user(request: Request) -> Optional[dict]:
    return request.session.get("user")


async def get_admin_user(request: Request, db: AsyncSession = Depends(get_async_session)) -> dict:
    user = await get_current_user(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Please open via Telegram Mini App."
        )

    telegram_id = user.get("telegram_id")
    if telegram_id not in ADMIN_TELEGRAM_IDS:
        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )

    return user


@router.post("/auth")
async def admin_auth(
        request: Request,
        authorization: Optional[str] = Header(None),
        db: AsyncSession = Depends(get_async_session)
):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "tma":
        raise HTTPException(status_code=401, detail="Invalid Authorization format")

    init_data = parts[1]

    try:
        validate(init_data, BOT_TOKEN)
        parsed_data = parse(init_data)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Validation failed: {str(e)}")

    user_data = parsed_data.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="User data missing")

    telegram_id = user_data.get("id")

    if telegram_id not in ADMIN_TELEGRAM_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    request.session["user"] = {
        "telegram_id": telegram_id,
        "username": user_data.get("username") or user.username,
        "first_name": user_data.get("first_name", "")
    }

    logger.info(f"Admin {telegram_id} authenticated")
    return {"success": True}


@router.post("/logout")
async def admin_logout(request: Request):
    user = request.session.get("user")
    if user:
        logger.info(f"Admin {user.get('telegram_id')} logged out")
    request.session.clear()
    return {"success": True, "message": "Logged out"}


@router.get("/", response_class=HTMLResponse)
async def admin_index(
        request: Request,
        db: AsyncSession = Depends(get_async_session)
):
    admin = await get_current_user(request)

    if not admin:
        return templates.TemplateResponse(
            "prompts.html",
            {
                "request": request,
                "prompts_by_category": {},
                "category_names": PROMPT_CATEGORIES,
                "admin": None
            }
        )

    if admin.get("telegram_id") not in ADMIN_TELEGRAM_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(select(Prompt).order_by(Prompt.category, Prompt.key))
    prompts = result.scalars().all()

    prompts_by_category = {}
    for prompt in prompts:
        if prompt.key in HIDDEN_PROMPT_KEYS:
            continue
        category = prompt.category
        if category not in prompts_by_category:
            prompts_by_category[category] = []
        prompts_by_category[category].append(prompt)

    return templates.TemplateResponse(
        "prompts.html",
        {
            "request": request,
            "prompts_by_category": prompts_by_category,
            "category_names": PROMPT_CATEGORIES,
            "admin": admin
        }
    )


@router.get("/prompts/{key}", response_class=HTMLResponse)
async def edit_prompt_form(
        key: str,
        request: Request,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    if key in HIDDEN_PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Prompt '{key}' not found")

    result = await db.execute(select(Prompt).where(Prompt.key == key))
    prompt = result.scalar_one_or_none()

    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt '{key}' not found")

    return templates.TemplateResponse(
        "edit.html",
        {
            "request": request,
            "prompt": prompt,
            "admin": admin
        }
    )


@router.post("/prompts/{key}")
async def update_prompt(
        key: str,
        request: Request,
        content: str = Form(...),
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    if key in HIDDEN_PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Prompt '{key}' not found")

    result = await db.execute(select(Prompt).where(Prompt.key == key))
    prompt = result.scalar_one_or_none()

    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt '{key}' not found")

    await db.execute(
        update(Prompt)
        .where(Prompt.key == key)
        .values(content=content)
    )
    await db.commit()

    await reload_cache(key, content)
    await invalidate_character_modifiers_cache()

    logger.info(f"Admin {admin.get('telegram_id')} updated prompt '{key}'")

    return RedirectResponse(url="/admin/", status_code=303)


@router.post("/prompts/{key}/reset")
async def reset_prompt(
        key: str,
        request: Request,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    if key in HIDDEN_PROMPT_KEYS:
        raise HTTPException(status_code=404, detail=f"Prompt '{key}' not found")

    if key not in DEFAULT_PROMPTS:
        raise HTTPException(status_code=404, detail=f"No default value for prompt '{key}'")

    default_content = DEFAULT_PROMPTS[key]

    result = await db.execute(select(Prompt).where(Prompt.key == key))
    prompt = result.scalar_one_or_none()

    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt '{key}' not found")

    await db.execute(
        update(Prompt)
        .where(Prompt.key == key)
        .values(content=default_content)
    )
    await db.commit()

    await reload_cache(key, default_content)
    await invalidate_character_modifiers_cache()

    logger.info(f"Admin {admin.get('telegram_id')} reset prompt '{key}' to default")

    return RedirectResponse(url=f"/admin/prompts/{key}", status_code=303)


@router.get("/characters", response_class=HTMLResponse)
async def list_characters(
        request: Request,
        db: AsyncSession = Depends(get_async_session)
):
    admin = await get_current_user(request)

    if not admin:
        return templates.TemplateResponse(
            "characters.html",
            {
                "request": request,
                "characters": [],
                "admin": None
            }
        )

    if admin.get("telegram_id") not in ADMIN_TELEGRAM_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(select(Character).order_by(Character.name))
    characters = result.scalars().all()

    return templates.TemplateResponse(
        "characters.html",
        {
            "request": request,
            "characters": characters,
            "admin": admin
        }
    )


@router.delete("/api/characters/{character_id}")
async def admin_delete_character(
        character_id: str,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # Удаляем все чаты с этим персонажем (сообщения/картинки каскадно)
    chats_result = await db.execute(
        select(Chat).where(Chat.chat_type == "character", Chat.target_id == character_id)
    )
    chats = chats_result.scalars().all()
    chat_ids = [c.id for c in chats]

    paths = await collect_character_file_paths(db, character_id, chat_ids)

    cache = get_cache()
    for chat in chats:
        await db.delete(chat)
        if cache:
            await cache.invalidate_chat_state(chat.id)

    await db.delete(character)
    await db.commit()
    delete_files(paths)

    await invalidate_character_modifiers_cache()
    if cache:
        await cache.invalidate_character(character_id)

    return {"success": True}


@router.get("/api/check-character-id/{character_id}")
async def check_character_id(
        character_id: str,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()
    return {"exists": character is not None}


@router.get("/api/check-world-id/{world_id}")
async def check_world_id(
        world_id: str,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    result = await db.execute(select(World).where(World.id == world_id))
    world = result.scalar_one_or_none()
    return {"exists": world is not None}


@router.get("/characters/new", response_class=HTMLResponse)
async def add_character_form(
        request: Request,
        admin: dict = Depends(get_admin_user)
):
    return templates.TemplateResponse(
        "add_character.html",
        {
            "request": request,
            "admin": admin
        }
    )


@router.post("/characters/new")
async def create_character(
        request: Request,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    form_data = await request.form()

    character_id = form_data.get("id", "").strip()
    name = form_data.get("name", "").strip()
    short_description = form_data.get("short_description", "").strip()
    description = form_data.get("description", "").strip()
    personality = form_data.get("personality", "").strip()
    scenario = form_data.get("scenario", "").strip()
    first_message = form_data.get("first_message", "").strip()
    tags_str = form_data.get("tags", "").strip()
    is_nsfw = form_data.get("is_nsfw") == "on"
    is_verified = form_data.get("is_verified") == "on"
    model_type = form_data.get("model_type", "anime")
    gender = form_data.get("gender", "female")

    try:
        validate_model_gender(model_type, gender)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not character_id or not name or not description or not personality or not scenario or not first_message:
        raise HTTPException(status_code=400, detail="All main fields are required")

    if not re.match(r'^[a-z0-9_-]+$', character_id):
        raise HTTPException(status_code=400,
                            detail="ID must contain only lowercase letters, numbers, hyphens and underscores")

    result = await db.execute(select(Character).where(Character.id == character_id))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"Character with ID '{character_id}' already exists")

    wardrobe_keys = form_data.getlist("wardrobe_key")
    wardrobe_values = form_data.getlist("wardrobe_value")
    wardrobe = {
        k.strip(): v.strip()
        for k, v in zip(wardrobe_keys, wardrobe_values)
        if k.strip()
    }
    # Auto-add required wardrobe keys if missing
    if gender == "male":
        wardrobe.setdefault("nude", "nothing, showing his naked body")
        wardrobe.setdefault("underwear", "black boxer briefs")
    else:
        wardrobe.setdefault("nude", "nothing, showing her naked body")
        wardrobe.setdefault("underwear", "white bra, white panties")

    visual_data = {
        "model_type": model_type,
        "gender": gender,
        "appearance": form_data.get("appearance", "").strip(),
        "body": form_data.get("visual_body", "").strip(),
        "face": form_data.get("visual_face", "").strip(),
        "default_outfit": form_data.get("visual_default_outfit", "").strip(),
        "style_tags": form_data.get("visual_style_tags", "").strip(),
        "wardrobe": wardrobe,
    }

    tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]

    alternate_greetings = []
    if "alternate_greeting" in form_data:
        alt_values = form_data.getlist("alternate_greeting")
        alternate_greetings = [v.strip() for v in alt_values if v.strip()]

    heat_level = int(form_data.get("heat_level", "0"))

    scenarios = [
        {
            "index": 0,
            "scenario": scenario,
            "intro": first_message,
            "heat_level": heat_level
        }
    ]

    for idx, alt_greeting in enumerate(alternate_greetings, start=1):
        scenarios.append({
            "index": idx,
            "scenario": scenario,
            "intro": alt_greeting,
            "heat_level": heat_level
        })

    author_type = form_data.get("author_type", "aikai")
    if author_type == "custom":
        created_by_username = form_data.get("created_by_username", "").strip() or None
    else:
        created_by_username = "AiKai Team"

    is_public = form_data.get("is_public") == "on"
    if author_type != "custom":
        is_public = True
    if is_verified and not is_public:
        is_verified = False
    if is_verified:
        is_public = True

    new_character = Character(
        id=character_id,
        name=name,
        short_description=short_description,
        description=description,
        personality=personality,
        visual_data=visual_data,
        scenarios=scenarios,
        tags=tags,
        is_nsfw=is_nsfw,
        created_by_username=created_by_username,
        is_public=is_public,
        is_verified=is_verified,
    )

    db.add(new_character)
    await db.commit()

    modifiers = {
        1: form_data.get("modifier_stage_1", "").strip(),
        2: form_data.get("modifier_stage_2", "").strip(),
        3: form_data.get("modifier_stage_3", "").strip(),
        4: form_data.get("modifier_stage_4", "").strip(),
    }
    await create_or_update_character_modifiers(
        character_id=character_id,
        character_name=name,
        is_nsfw=is_nsfw,
        modifiers=modifiers,
        db=db,
        gender=gender,
    )
    await db.commit()
    await invalidate_character_modifiers_cache()

    cache = get_cache()
    if cache:
        await cache.invalidate_character(character_id)

    logger.info(f"Admin {admin.get('telegram_id')} created character '{character_id}'")

    return RedirectResponse(url="/admin/characters", status_code=303)


@router.get("/characters/{character_id}", response_class=HTMLResponse)
async def edit_character_form(
        character_id: str,
        request: Request,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")

    scenario_text = ""
    first_message = ""
    alternate_greetings = []
    heat_level = 0

    if character.scenarios and len(character.scenarios) > 0:
        first_scenario = character.scenarios[0]
        scenario_text = first_scenario.get("scenario", "")
        first_message = first_scenario.get("intro", "")
        heat_level = first_scenario.get("heat_level", 0)

        for i in range(1, len(character.scenarios)):
            alternate_greetings.append(character.scenarios[i].get("intro", ""))

    visual_data_json = json.dumps(character.visual_data, indent=2, ensure_ascii=False)

    modifiers = await get_character_modifiers_from_db(character_id, db)

    return templates.TemplateResponse(
        "edit_character.html",
        {
            "request": request,
            "character": character,
            "scenario_text": scenario_text,
            "first_message": first_message,
            "alternate_greetings": alternate_greetings,
            "heat_level": heat_level,
            "visual_data_json": visual_data_json,
            "modifiers": modifiers,
            "admin": admin
        }
    )


@router.post("/characters/{character_id}")
async def update_character(
        character_id: str,
        request: Request,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()

    if not character:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")

    form_data = await request.form()

    name = form_data.get("name", "").strip()
    short_description = form_data.get("short_description", "").strip()
    description = form_data.get("description", "").strip()
    personality = form_data.get("personality", "").strip()
    scenario = form_data.get("scenario", "").strip()
    first_message = form_data.get("first_message", "").strip()
    visual_data_str = form_data.get("visual_data", "").strip()
    tags_str = form_data.get("tags", "").strip()
    is_nsfw = form_data.get("is_nsfw") == "on"
    is_verified = form_data.get("is_verified") == "on"
    is_public = form_data.get("is_public") == "on"

    # Process author
    author_type = form_data.get("author_type", "aikai")
    if author_type == "custom":
        created_by_username = form_data.get("created_by_username", "").strip() or None
        created_by_username_id_update = None
    else:
        created_by_username = None
        created_by_username_id_update = None

    if not name or not description or not personality or not scenario or not first_message:
        raise HTTPException(status_code=400, detail="All main fields are required")

    try:
        visual_data = json.loads(visual_data_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in visual_data: {str(e)}")

    try:
        validate_model_gender(visual_data.get("model_type", "anime"), visual_data.get("gender", "female"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]

    alternate_greetings = []
    for key, value in form_data.items():
        if key == "alternate_greeting":
            if isinstance(value, str) and value.strip():
                alternate_greetings.append(value.strip())

    if "alternate_greeting" in form_data:
        alt_values = form_data.getlist("alternate_greeting")
        alternate_greetings = [v.strip() for v in alt_values if v.strip()]

    heat_level = int(form_data.get("heat_level", "0"))

    scenarios = [
        {
            "index": 0,
            "scenario": scenario,
            "intro": first_message,
            "heat_level": heat_level
        }
    ]

    for idx, alt_greeting in enumerate(alternate_greetings, start=1):
        scenarios.append({
            "index": idx,
            "scenario": scenario,
            "intro": alt_greeting,
            "heat_level": heat_level
        })

    if author_type != "custom":
        is_public = True
    if is_verified and not is_public:
        is_verified = False
    if is_verified:
        is_public = True

    update_values = dict(
        name=name,
        short_description=short_description,
        description=description,
        personality=personality,
        visual_data=visual_data,
        scenarios=scenarios,
        tags=tags,
        is_nsfw=is_nsfw,
        is_public=is_public,
        is_verified=is_verified,
        created_by_username=created_by_username,
        created_by_username_id=created_by_username_id_update,
    )

    await db.execute(
        update(Character)
        .where(Character.id == character_id)
        .values(**update_values)
    )
    await db.commit()

    logger.info(f"[UPDATE_CHARACTER] saved to DB, visual_data avatar={json.dumps(visual_data.get('avatar'))}")

    cache = get_cache()
    if cache:
        await cache.invalidate_character(character_id)
        logger.info(f"[UPDATE_CHARACTER] cache invalidated for {character_id}")

    # Обновить модификаторы стадий
    modifiers = {
        1: form_data.get("modifier_stage_1", "").strip(),
        2: form_data.get("modifier_stage_2", "").strip(),
        3: form_data.get("modifier_stage_3", "").strip(),
        4: form_data.get("modifier_stage_4", "").strip(),
    }
    await create_or_update_character_modifiers(
        character_id=character_id,
        character_name=name,
        is_nsfw=is_nsfw,
        modifiers=modifiers,
        db=db,
        gender=visual_data.get("gender", "female"),
    )
    await db.commit()
    await invalidate_character_modifiers_cache()

    cache = get_cache()
    if cache:
        await cache.invalidate_character(character_id)

    logger.info(f"Admin {admin.get('telegram_id')} updated character '{character_id}'")

    return RedirectResponse(url="/admin/characters", status_code=303)


@router.get("/worlds", response_class=HTMLResponse)
async def list_worlds(
        request: Request,
        db: AsyncSession = Depends(get_async_session)
):
    admin = await get_current_user(request)

    if not admin:
        return templates.TemplateResponse(
            "worlds.html",
            {
                "request": request,
                "worlds": [],
                "admin": None
            }
        )

    if admin.get("telegram_id") not in ADMIN_TELEGRAM_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(select(World).order_by(World.name))
    worlds = result.scalars().all()

    return templates.TemplateResponse(
        "worlds.html",
        {
            "request": request,
            "worlds": worlds,
            "admin": admin
        }
    )


@router.get("/worlds/new", response_class=HTMLResponse)
async def add_world_form(
        request: Request,
        admin: dict = Depends(get_admin_user)
):
    return templates.TemplateResponse(
        "add_world.html",
        {
            "request": request,
            "admin": admin
        }
    )


@router.post("/worlds/new")
async def create_world(
        request: Request,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    form_data = await request.form()

    world_id = form_data.get("id", "").strip()
    name = form_data.get("name", "").strip()
    short_description = form_data.get("short_description", "").strip()
    description = form_data.get("description", "").strip()
    gm_instructions = form_data.get("gm_instructions", "").strip()
    intro_message = form_data.get("intro_message", "").strip()
    cover_image = form_data.get("cover_image", "").strip() or None
    tags_str = form_data.get("tags", "").strip()

    if not world_id or not name or not description or not intro_message:
        raise HTTPException(status_code=400, detail="ID, name, description, and intro message are required")

    if not re.match(r'^[a-z0-9_-]+$', world_id):
        raise HTTPException(status_code=400,
                            detail="ID must contain only lowercase letters, numbers, hyphens and underscores")

    result = await db.execute(select(World).where(World.id == world_id))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"World with ID '{world_id}' already exists")

    tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]

    alt_titles = form_data.getlist("alt_scenario_title")
    alt_intros = form_data.getlist("alt_scenario_intro")
    alt_gm_instructions = form_data.getlist("alt_scenario_gm_instructions")

    scenarios = [
        {
            "index": 0,
            "intro": intro_message,
            "gm_instructions": gm_instructions
        }
    ]

    for idx in range(len(alt_titles)):
        title = alt_titles[idx].strip() if idx < len(alt_titles) else ""
        intro = alt_intros[idx].strip() if idx < len(alt_intros) else ""
        gm_instr = alt_gm_instructions[idx].strip() if idx < len(alt_gm_instructions) else ""

        if title or intro:
            scenarios.append({
                "index": idx + 1,
                "title": title,
                "intro": intro,
                "gm_instructions": gm_instr
            })

    saved_cover_image = None
    if cover_image:
        try:
            cover_path = await save_world_cover(cover_image, world_id)
            saved_cover_image = get_public_url(cover_path)
        except Exception as e:
            logger.warning(f"Failed to save world cover, using original URL: {e}")
            saved_cover_image = cover_image

    new_world = World(
        id=world_id,
        name=name,
        short_description=short_description,
        description=description,
        cover_image=saved_cover_image,
        scenarios=scenarios,
        locations=[],
        tags=tags,
        is_nsfw=False,
        is_public=True,
        is_verified=True,
    )

    db.add(new_world)
    await db.commit()

    cache = get_cache()
    if cache:
        await cache.invalidate_world(world_id)

    logger.info(f"Admin {admin.get('telegram_id')} created world '{world_id}'")

    return RedirectResponse(url="/admin/worlds", status_code=303)


@router.get("/worlds/{world_id}", response_class=HTMLResponse)
async def edit_world_form(
        world_id: str,
        request: Request,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    result = await db.execute(select(World).where(World.id == world_id))
    world = result.scalar_one_or_none()

    if not world:
        raise HTTPException(status_code=404, detail=f"World '{world_id}' not found")

    gm_instructions = ""
    intro_message = ""
    alternate_scenarios = []

    if world.scenarios and len(world.scenarios) > 0:
        first_scenario = world.scenarios[0]
        gm_instructions = first_scenario.get("gm_instructions", "")
        intro_message = first_scenario.get("intro", "")

        for i in range(1, len(world.scenarios)):
            alt_scenario = world.scenarios[i]
            alternate_scenarios.append({
                "title": alt_scenario.get("title", ""),
                "intro": alt_scenario.get("intro", ""),
                "gm_instructions": alt_scenario.get("gm_instructions", "")
            })

    return templates.TemplateResponse(
        "edit_world.html",
        {
            "request": request,
            "world": world,
            "gm_instructions": gm_instructions,
            "intro_message": intro_message,
            "alternate_scenarios": alternate_scenarios,
            "admin": admin
        }
    )


@router.post("/worlds/{world_id}")
async def update_world(
        world_id: str,
        request: Request,
        db: AsyncSession = Depends(get_async_session),
        admin: dict = Depends(get_admin_user)
):
    result = await db.execute(select(World).where(World.id == world_id))
    world = result.scalar_one_or_none()

    if not world:
        raise HTTPException(status_code=404, detail=f"World '{world_id}' not found")

    form_data = await request.form()

    name = form_data.get("name", "").strip()
    short_description = form_data.get("short_description", "").strip()
    description = form_data.get("description", "").strip()
    gm_instructions = form_data.get("gm_instructions", "").strip()
    intro_message = form_data.get("intro_message", "").strip()
    tags_str = form_data.get("tags", "").strip()
    is_nsfw = form_data.get("is_nsfw") == "on"
    is_verified = form_data.get("is_verified") == "on"
    is_public = form_data.get("is_public") == "on"

    if is_verified and not is_public:
        is_verified = False
    if is_verified:
        is_public = True

    if not name or not description or not intro_message:
        raise HTTPException(status_code=400, detail="Name, description, and intro message are required")

    tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]

    alt_titles = form_data.getlist("alt_scenario_title")
    alt_intros = form_data.getlist("alt_scenario_intro")
    alt_gm_instructions = form_data.getlist("alt_scenario_gm_instructions")

    scenarios = [
        {
            "index": 0,
            "intro": intro_message,
            "gm_instructions": gm_instructions
        }
    ]

    for idx in range(len(alt_titles)):
        title = alt_titles[idx].strip() if idx < len(alt_titles) else ""
        intro = alt_intros[idx].strip() if idx < len(alt_intros) else ""
        gm_instr = alt_gm_instructions[idx].strip() if idx < len(alt_gm_instructions) else ""

        if title or intro:
            scenarios.append({
                "index": idx + 1,
                "title": title,
                "intro": intro,
                "gm_instructions": gm_instr
            })

    cover_image_url = form_data.get("cover_image", "").strip() or None
    new_cover_image = world.cover_image
    if cover_image_url:
        try:
            cover_path = await save_world_cover(cover_image_url, world_id)
            new_cover_image = get_public_url(cover_path)
        except Exception as e:
            logger.warning(f"Failed to save world cover: {e}, using provided URL")
            new_cover_image = cover_image_url

    await db.execute(
        update(World)
        .where(World.id == world_id)
        .values(
            name=name,
            short_description=short_description,
            description=description,
            cover_image=new_cover_image,
            scenarios=scenarios,
            tags=tags,
            is_nsfw=is_nsfw,
            is_verified=is_verified,
            is_public=is_public,
        )
    )
    await db.commit()

    cache = get_cache()
    if cache:
        await cache.invalidate_world(world_id)

    logger.info(f"Admin {admin.get('telegram_id')} updated world '{world_id}'")

    return RedirectResponse(url="/admin/worlds", status_code=303)


@router.get("/stats", response_class=HTMLResponse)
async def statistics_page(
        request: Request,
        db: AsyncSession = Depends(get_async_session),
        page: int = Query(default=1, ge=1),
        search: str = Query(default=""),
):
    admin = await get_current_user(request)

    if not admin:
        return templates.TemplateResponse(
            "stats.html",
            {
                "request": request,
                "admin": None
            }
        )

    if admin.get("telegram_id") not in ADMIN_TELEGRAM_IDS:
        # fixme - оставь так
        pass
        # raise HTTPException(status_code=403, detail="Admin access required")

    total_users = await StatisticsService.get_all_users_count(db)
    users_with_chats = await StatisticsService.get_users_with_chats(db)
    top_characters = await StatisticsService.get_top_characters_info(db, head=10)
    top_worlds = await StatisticsService.get_top_worlds_info(db, head=10)
    churn_summary = await StatisticsService.get_churned_users_summary(db, days_threshold=7)
    users_data = await StatisticsService.get_users_table(db, page=page, per_page=50, search=search)

    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "admin": admin,
            "total_users": total_users,
            "users_with_chats": users_with_chats,
            "top_characters": top_characters,
            "top_worlds": top_worlds,
            "churn_summary": churn_summary,
            "users_data": users_data,
            "search": search,
        }
    )


class SetPlanRequest(BaseModel):
    user_ids: list[int]
    plan: str


class AddBonusRequest(BaseModel):
    user_ids: list[int]
    bonus: dict[str, int]


@router.post("/api/users/set-plan")
async def admin_set_user_plan(
        body: SetPlanRequest,
        request: Request,
        db: AsyncSession = Depends(get_async_session),
):
    admin = await get_current_user(request)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        plan = SubscriptionPlan(body.plan)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    sub_service = get_subscription_service()
    updated = 0
    for uid in body.user_ids:
        try:
            await sub_service.activate_subscription(uid, plan, db)
            updated += 1
        except Exception:
            pass

    return JSONResponse({"ok": True, "updated": updated})


@router.post("/api/users/add-bonus")
async def admin_add_user_bonus(
        body: AddBonusRequest,
        request: Request,
        db: AsyncSession = Depends(get_async_session),
):
    admin = await get_current_user(request)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Маппим usage_type → bonus_db_field
    bonus_db: dict[str, int] = {}
    for usage_type, amount in body.bonus.items():
        if amount <= 0:
            continue
        db_field = USAGE_TYPE_MAP.get(usage_type)
        if not db_field:
            raise HTTPException(status_code=400, detail=f"Unknown usage type: {usage_type}")
        bonus_db[f"bonus_{db_field}"] = amount

    if not bonus_db:
        return JSONResponse({"ok": True, "updated": 0})

    period = _dt.utcnow().strftime("%Y-%m")
    repo = SubscriptionRepository(db)
    updated = 0
    for uid in body.user_ids:
        try:
            await repo.set_bonus_limits(uid, period, bonus_db)
            updated += 1
        except Exception:
            pass

    return JSONResponse({"ok": True, "updated": updated})
