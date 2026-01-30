from fastapi import APIRouter, Request, HTTPException, Depends, Form, Header
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging
import json
import re

from shared.models import Prompt, User, Character, World, get_async_session
from shared.config import ADMIN_TELEGRAM_IDS, BOT_TOKEN
from shared.services.prompt_service import reload_cache_sync, DEFAULT_PROMPTS
from shared.constants import invalidate_character_modifiers_cache
from api.image_gen.schemas.generate import invalidate_nsfw_levels_cache, Prompt as ImagePrompt
from api.image_gen.services.generate import submit_anime, submit_real
from services.image_storage import save_avatar, get_public_url
from telegram_init_data import validate, parse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="admin/templates")


PROMPT_CATEGORIES = {
    "character": "Character Prompts",
    "player": "Player Prompts",
    "summary": "Summary Prompts",
    "scene_analysis": "Scene Analysis",
    "creation": "Character Creation",
    "image": "Image Generation",
    "modifiers": "Character Modifiers",
}


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

    reload_cache_sync(key, content)
    invalidate_character_modifiers_cache()
    invalidate_nsfw_levels_cache()

    logger.info(f"Admin {admin.get('telegram_id')} updated prompt '{key}'")

    return RedirectResponse(url="/admin/", status_code=303)


@router.post("/prompts/{key}/reset")
async def reset_prompt(
    key: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    admin: dict = Depends(get_admin_user)
):
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

    reload_cache_sync(key, default_content)
    invalidate_character_modifiers_cache()
    invalidate_nsfw_levels_cache()

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


@router.get("/api/check-character-id/{character_id}")
async def check_character_id(
    character_id: str,
    db: AsyncSession = Depends(get_async_session),
    admin: dict = Depends(get_admin_user)
):
    """Check if a character ID already exists"""
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()
    return {"exists": character is not None}


@router.post("/api/generate-avatar")
async def generate_avatar(
    request: Request,
    admin: dict = Depends(get_admin_user)
):
    """Generate preview avatar from visual data"""
    data = await request.json()

    model_type = data.get("model_type", "anime")
    appearance = data.get("appearance", "")
    body = data.get("body", "")
    face = data.get("face", "")
    default_outfit = data.get("default_outfit", "")
    style_tags = data.get("style_tags", "")

    prompt = ImagePrompt(
        character_base=", ".join(filter(None, [appearance, body])),
        facial_expression=face,
        clothing=default_outfit,
        style=style_tags,
        nsfw_level=0
    )

    pos, neg = prompt.build_prompt(model_type)

    try:
        if model_type == "real":
            image_url = await submit_real(prompt=pos, allow_nsfw=False, nsfw_level=0)
        else:
            image_url = await submit_anime(pos, neg)

        if not image_url:
            raise HTTPException(status_code=500, detail="Image generation failed")

        return {"url": image_url, "prompt": pos}
    except Exception as e:
        logger.error(f"Avatar generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


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
    description = form_data.get("description", "").strip()
    personality = form_data.get("personality", "").strip()
    scenario = form_data.get("scenario", "").strip()
    first_message = form_data.get("first_message", "").strip()
    tags_str = form_data.get("tags", "").strip()
    is_nsfw = form_data.get("is_nsfw") == "on"

    if not character_id or not name or not description or not personality or not scenario or not first_message:
        raise HTTPException(status_code=400, detail="All main fields are required")

    if not re.match(r'^[a-z0-9_-]+$', character_id):
        raise HTTPException(status_code=400, detail="ID must contain only lowercase letters, numbers, hyphens and underscores")

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

    visual_data = {
        "model_type": form_data.get("model_type", "anime"),
        "appearance": form_data.get("appearance", "").strip(),
        "body": form_data.get("visual_body", "").strip(),
        "face": form_data.get("visual_face", "").strip(),
        "default_outfit": form_data.get("visual_default_outfit", "").strip(),
        "style_tags": form_data.get("visual_style_tags", "").strip(),
        "wardrobe": wardrobe
    }

    avatar_url = form_data.get("avatar_url", "").strip()
    if avatar_url:
        try:
            avatar_path = await save_avatar(avatar_url, character_id)
            visual_data["avatar"] = f"/images/{avatar_path}"
        except Exception as e:
            logger.warning(f"Failed to save avatar: {e}, using provider URL")
            visual_data["avatar"] = avatar_url

    tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]

    alternate_greetings = []
    if "alternate_greeting" in form_data:
        alt_values = form_data.getlist("alternate_greeting")
        alternate_greetings = [v.strip() for v in alt_values if v.strip()]

    scenarios = [
        {
            "index": 0,
            "scenario": scenario,
            "intro": first_message
        }
    ]

    for idx, alt_greeting in enumerate(alternate_greetings, start=1):
        scenarios.append({
            "index": idx,
            "scenario": scenario,
            "intro": alt_greeting
        })

    author_type = form_data.get("author_type", "aikai")
    if author_type == "custom":
        created_by_username = form_data.get("created_by_username", "").strip() or None
    else:
        created_by_username = "AiKai Team"

    new_character = Character(
        id=character_id,
        name=name,
        description=description,
        personality=personality,
        visual_data=visual_data,
        scenarios=scenarios,
        tags=tags,
        is_nsfw=is_nsfw,
        created_by_username=created_by_username
    )

    db.add(new_character)
    await db.commit()

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

    if character.scenarios and len(character.scenarios) > 0:
        first_scenario = character.scenarios[0]
        scenario_text = first_scenario.get("scenario", "")
        first_message = first_scenario.get("intro", "")

        for i in range(1, len(character.scenarios)):
            alternate_greetings.append(character.scenarios[i].get("intro", ""))

    visual_data_json = json.dumps(character.visual_data, indent=2, ensure_ascii=False)

    return templates.TemplateResponse(
        "edit_character.html",
        {
            "request": request,
            "character": character,
            "scenario_text": scenario_text,
            "first_message": first_message,
            "alternate_greetings": alternate_greetings,
            "visual_data_json": visual_data_json,
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
    description = form_data.get("description", "").strip()
    personality = form_data.get("personality", "").strip()
    scenario = form_data.get("scenario", "").strip()
    first_message = form_data.get("first_message", "").strip()
    visual_data_str = form_data.get("visual_data", "").strip()
    tags_str = form_data.get("tags", "").strip()
    is_nsfw = form_data.get("is_nsfw") == "on"

    if not name or not description or not personality or not scenario or not first_message:
        raise HTTPException(status_code=400, detail="All main fields are required")

    try:
        visual_data = json.loads(visual_data_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in visual_data: {str(e)}")

    tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]

    alternate_greetings = []
    for key, value in form_data.items():
        if key == "alternate_greeting":
            if isinstance(value, str) and value.strip():
                alternate_greetings.append(value.strip())

    if "alternate_greeting" in form_data:
        alt_values = form_data.getlist("alternate_greeting")
        alternate_greetings = [v.strip() for v in alt_values if v.strip()]

    scenarios = [
        {
            "index": 0,
            "scenario": scenario,
            "intro": first_message
        }
    ]

    for idx, alt_greeting in enumerate(alternate_greetings, start=1):
        scenarios.append({
            "index": idx,
            "scenario": scenario,
            "intro": alt_greeting
        })

    await db.execute(
        update(Character)
        .where(Character.id == character_id)
        .values(
            name=name,
            description=description,
            personality=personality,
            visual_data=visual_data,
            scenarios=scenarios,
            tags=tags,
            is_nsfw=is_nsfw
        )
    )
    await db.commit()

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
    description = form_data.get("description", "").strip()
    gm_instructions = form_data.get("gm_instructions", "").strip()
    intro_message = form_data.get("intro_message", "").strip()
    tags_str = form_data.get("tags", "").strip()
    is_nsfw = form_data.get("is_nsfw") == "on"

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

    await db.execute(
        update(World)
        .where(World.id == world_id)
        .values(
            name=name,
            description=description,
            scenarios=scenarios,
            tags=tags,
            is_nsfw=is_nsfw
        )
    )
    await db.commit()

    logger.info(f"Admin {admin.get('telegram_id')} updated world '{world_id}'")

    return RedirectResponse(url="/admin/worlds", status_code=303)
