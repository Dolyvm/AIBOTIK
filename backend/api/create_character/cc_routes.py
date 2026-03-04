import json
import logging
import uuid
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, Body, Depends

from shared.config import SCENE_ANALYZER_MODEL, STRUCTURED_MODEL
from shared.services.analytics import AnalyticsService
from shared.services.llm import LLMClient
from shared.services.rate_limiter import get_rate_limiter, RateLimitExceeded, RATE_LIMITS
from shared.services.cache import get_cache
from shared.services.prompt_service import get_prompt
from .cc_schemas import CreateCharacterRequest, CreateCharacterFromPromptRequest
from .cc_service import (
    stepsGroups,
    build_llm_prompt,
    build_description_prompt,
    build_first_mes_prompt,
    generate_tags,
    build_personality_with_preferences,
    build_create_character_prompt, fix_generated_fields, fix_mojibake
)

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.models import User, Character
from shared.database import get_session
from auth.telegram_auth import get_current_user
from auth.authorization import verify_chat_ownership

router = APIRouter(prefix="/api/create_character", tags=["create_character"])


@router.post("")
async def create_character_endpoint(
        payload: CreateCharacterRequest = Body(...),
        user: User = Depends(get_current_user)
):
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        limits = RATE_LIMITS["character_creation"]
        allowed = await rate_limiter.is_allowed(
            key=f"character_creation:user:{user.telegram_id}",
            limit=limits["limit"],
            window=limits["window"]
        )
        if not allowed:
            raise RateLimitExceeded(
                limit=limits["limit"],
                window=limits["window"],
                retry_after=limits["retry_after"]
            )

    try:
        character_id = f"custom_{user.telegram_id}_{uuid.uuid4().hex[:8]}"

        scenarios = []
        if payload.first_mes or payload.scenario:
            scenarios.append({
                "index": 0,
                "intro": payload.first_mes or "",
                "scenario": payload.scenario or ""
            })

        tags = generate_tags(payload)

        personality = build_personality_with_preferences(payload)

        description = payload.description or (
            f"{payload.name} — {payload.age}-летняя девушка. "
            f"Характер: {payload.personality}."
        )

        async with get_session() as session:
            character = Character(
                id=character_id,
                name=payload.name,
                short_description=payload.short_description or "",
                is_public=payload.is_public,
                description=description,
                personality=personality,
                visual_data=payload.build_visual(),
                scenarios=scenarios,
                tags=tags,
                is_nsfw=True,
                created_by_username_id=user.telegram_id,
                created_by_username=user.username,
            )
            session.add(character)
            await session.commit()

            await AnalyticsService.track(
                session,
                user_id=user.telegram_id,
                event_type="create_character",
                entity_type="characters",
                entity_id=str(character_id),
            )

        cache = get_cache()
        if cache:
            await cache.invalidate_character(character_id)

        return {"character_id": character_id, "status": "created"}
    except Exception as e:
        logging.error(f"[CREATE_CHARACTER] Error: {e}")
        raise HTTPException(status_code=500, detail={
            "error": "creation_failed",
            "message": "Не удалось создать персонажа",
            "code": "CHARACTER_CREATION_FAILED"
        })


@router.get("")
async def get_create_character_data(user: User = Depends(get_current_user)):
    return {"groups": stepsGroups}


@router.post("/scenario")
async def generate_character_scenario(
        payload: CreateCharacterRequest = Body(...),
        user: User = Depends(get_current_user)
):
    rate_limiter = get_rate_limiter()
    if rate_limiter:
        allowed = await rate_limiter.check_llm_rate_limit(user.telegram_id)
        if not allowed:
            limits = RATE_LIMITS["llm"]
            raise RateLimitExceeded(
                limit=limits["limit"],
                window=limits["window"],
                retry_after=limits["retry_after"]
            )

    try:
        llm_client = LLMClient(model=SCENE_ANALYZER_MODEL)

        scenario_prompt = await build_llm_prompt(payload)
        scenario = await llm_client.generate(
            system_prompt=scenario_prompt,
            messages=[],
            max_tokens=500,
            temperature=0.75
        )

        first_mes_prompt = await build_first_mes_prompt(payload, scenario)
        first_mes = await llm_client.generate(
            system_prompt=first_mes_prompt,
            messages=[],
            max_tokens=800,
            temperature=0.75
        )

        description_prompt = await build_description_prompt(payload)
        description = await llm_client.generate(
            system_prompt=description_prompt,
            messages=[],
            max_tokens=500,
            temperature=0.7
        )

        return {
            "scenario": scenario,
            "first_mes": first_mes,
            "description": description
        }
    except Exception as e:
        logging.error(f"[CREATE_CHARACTER] LLM error: {e}")
        raise HTTPException(status_code=500, detail={
            "error": "generation_failed",
            "message": "Ошибка генерации сценария",
            "code": "SCENARIO_GENERATION_FAILED"
        })


@router.post("/create_character_from_prompt")
async def generate_character_from_prompt(
        payload: CreateCharacterFromPromptRequest = Body(...),
        user: User = Depends(get_current_user)
):
    # rate_limiter = get_rate_limiter()
    rate_limiter = None
    if rate_limiter:
        allowed = await rate_limiter.check_llm_rate_limit(user.telegram_id)
        if not allowed:
            limits = RATE_LIMITS["llm"]
            raise RateLimitExceeded(
                limit=limits["limit"],
                window=limits["window"],
                retry_after=limits["retry_after"]
            )

    try:
        system_prompt = await get_prompt("create_character_prompt")
        user_prompt = "Создай карточку персонажа на основе этого описания:\n\n"+payload.user_prompt
        response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "russian_language_character_card",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": [
                                    "string",
                                    "null"
                                ],
                                "description": "Имя персонажа, извлечённое из текста. Если имени нет — null."
                            },
                            "description": {
                                "type": "string",
                                "description": "Краткое, связное описание персонажа на русском языке (внешность + характер + немного фона)."
                            },
                            "visual": {
                                "type": "object",
                                "properties": {
                                    "llm_settings": {
                                        "type": "object",
                                        "properties": {
                                            "preferences": {
                                                "type": [
                                                    "string",
                                                    "null"
                                                ],
                                                "description": "Сексуальные предпочтения / фетиши, подходящие персонажу. Если не подходит — null. Примеры: anal sex, domination, gentle romance, etc."
                                            },
                                            "relationship_role": {
                                                "type": "string",
                                                "enum": [
                                                    "Падчерица",
                                                    "Мачеха",
                                                    "Любовница",
                                                    "Одноклассник",
                                                    "Коллега",
                                                    "Учитель",
                                                    "Девушка",
                                                    "Друзья с привилегиями",
                                                    "Жена",
                                                    "Друг"
                                                ],
                                                "description": "Роль в отношениях с пользователем. СТРОГО ИЗ ENUM СПИСКА. Обязательно на русском."
                                            }
                                        },
                                        "required": [
                                            "preferences",
                                            "relationship_role"
                                        ],
                                        "additionalProperties": False
                                    },
                                    "nationality": {
                                        "type": "string",
                                        "enum": [
                                            "american",
                                            "asian",
                                            "russian",
                                            "italian",
                                            "latin",
                                            "german",
                                            "japanese",
                                            "indian",
                                            "arab",
                                            "kazakh"
                                        ],
                                        "description": "Национальность из фиксированного списка, обязательно на английском. "
                                    },
                                    "age": {
                                        "type": "string",
                                        "enum": [
                                            "18",
                                            "25",
                                            "35",
                                            "45",
                                            "70"
                                        ],
                                        "description": "Возраст строго из списка (как строка)."
                                    },
                                    "ass": {
                                        "type": "string",
                                        "enum": [
                                            "small ass",
                                            "fit ass",
                                            "big round ass",
                                            "huge round ass"
                                        ],
                                        "description": "Строго из списка, обязательно на английском. "
                                    },
                                    "boobs": {
                                        "type": "string",
                                        "enum": [
                                            "small breasts",
                                            "beautiful breasts",
                                            "big breasts",
                                            "huge breasts"
                                        ],
                                        "description": "Строго из списка, обязательно на английском. "
                                    },
                                    "hair_color": {
                                        "type": "string",
                                        "enum": [
                                            "black",
                                            "brown",
                                            "blond",
                                            "grey",
                                            "white",
                                            "dark blue"
                                        ],
                                        "description": "Строго из списка, обязательно на английском. "
                                    },
                                    "haircut": {
                                        "type": "string",
                                        "enum": [
                                            "straight haircut",
                                            "braids haircut",
                                            "curly hair",
                                            "hair in bun",
                                            "pixie haircut",
                                            "ponytail hair",
                                            "two ponytails hair"
                                        ],
                                        "description": "Строго из списка, обязательно на английском. "
                                    },
                                    "eye_color": {
                                        "type": "string",
                                        "enum": [
                                            "brown",
                                            "blue",
                                            "green",
                                            "grey"
                                        ],
                                        "description": "Строго из списка, обязательно на английском. "
                                    },
                                    "body_type": {
                                        "type": "string",
                                        "enum": [
                                            "anorexic slender body",
                                            "petite slim body",
                                            "fit body",
                                            "curvy body",
                                            "fat body"
                                        ],
                                        "description": "Строго из списка!! обязательно на английском. "
                                    },
                                    "default_outfit": {
                                        "type": "string",
                                        "description": "Одежда по умолчанию в формате тегов через запятую, СТРОГО НА АНГЛИЙСКОМ ЯЗЫКЕ, например: 'cream colored knit sweater, blue jeans, simple gold stud earrings, hair in long single braid'"
                                    },
                                    "wardrobe": {
                                        "type": "object",
                                        "description": "Набор одежды по ситуациям. СТРОГО НА АНГЛИЙСКОМ ЯЗЫКЕ. Ключи — произвольные (casual, traditional, student и т.д.), значения — строка с тегами через запятую.",
                                        "additionalProperties": {
                                            "type": "string"
                                        },
                                        "minProperties": 1
                                    }
                                },
                                "required": [
                                    "llm_settings",
                                    "nationality",
                                    "age",
                                    "ass",
                                    "boobs",
                                    "hair_color",
                                    "haircut",
                                    "eye_color",
                                    "body_type",
                                    "default_outfit",
                                    "wardrobe"
                                ],
                                "additionalProperties": False
                            },
                            "personality": {
                                "type": "string",
                                "enum": [
                                    "Заботливый",
                                    "Мудрец",
                                    "Невинный",
                                    "Соблазнительница",
                                    "Доминант",
                                    "Покорный",
                                    "Любовник",
                                    "Фанатик",
                                    "Апатичный",
                                    "Доверенное лицо"
                                ],
                                "description": "Тип личности персонажа. СТРОГО ИЗ ENUM СПИСКА. Выбери наиболее подходящий тип исходя из описания."
                            },
                            "scenario": {
                                "type": "string",
                                "description": "Сценарий / обстоятельства знакомства с персонажем. На русском."
                            },
                            "first_mes": {
                                "type": "string",
                                "description": "Первое сообщение от персонажа. На русском, с *действиями* и речью в кавычках."
                            },
                            "alternate_greetings": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                },
                                "description": "Массив альтернативных приветствий. Каждое — полноценное сообщение на русском."
                            },
                            "example_dialogue": {
                                "type": "string",
                                "description": "Пример диалога в формате {{user}}: ...\\n{{char}}: ... На русском."
                            }
                        },
                        "required": [
                            "name",
                            "description",
                            "visual",
                            "personality",
                            "scenario",
                            "first_mes",
                            "alternate_greetings",
                            "example_dialogue"
                        ],
                        "additionalProperties": False
                    }
                }
            }
        # response_format = await get_prompt("create_character_output_schema")

        override_payload = {
            "model": "qwen/qwen3-30b-a3b-instruct-2507",
            # todo пересмотреть, мб нужно перенести messages в .generate() и все остальное тоже
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            "temperature": 0.3,
            "max_tokens": 4000,
            "response_format": response_format
        }
        llm_client = LLMClient(model=STRUCTURED_MODEL, override_payload=override_payload)

        cc_prompt = await build_create_character_prompt()

        raw_character = await llm_client.generate(
            system_prompt=cc_prompt,
            messages=[],
            max_tokens=4000,
            temperature=0.3
        )
        logging.info("raw_character")
        logging.info(raw_character)
        new_character: dict = json.loads(raw_character)
        visual = new_character.get("visual", {})
        preferences_str = visual.get("llm_settings", {}).get("preferences")
        if preferences_str:
            preferences = preferences_str.split(", ")
        else:
            preferences = None
        # Применяем mojibake-фикс к русским полям ДО валидации
        relationship_role = fix_mojibake(visual.get("llm_settings", {}).get("relationship_role"))
        personality_raw = fix_mojibake(new_character.get("personality"))

        create_character_data = fix_generated_fields({
                "name": new_character.get("name"),
                "age": visual.get("age"),
                "nationality": visual.get("nationality"),
                "eyes_color": visual.get("eye_color"),
                "hair_color": visual.get("hair_color"),
                "haircut": visual.get("haircut"),
                "body_type": visual.get("body_type"),
                "boobs_size": visual.get("boobs"),
                "ass_size": visual.get("ass"),
                "clothing": "Свободная рубашка",
                "personality": personality_raw,
                "relationship": relationship_role,
                "preferences": preferences,
            })

        # Переопределения от пользователя
        if payload.user_name:
            create_character_data["name"] = payload.user_name
        if payload.style:
            create_character_data["style"] = payload.style
        if payload.style == "anime":
            create_character_data["nationality"] = None  # аниме не использует национальность

        return {
            "createCharacterData": create_character_data,
            "newCharacterScenario":  new_character.get("scenario"),
            "newCharacterFirstMes": new_character.get("first_mes"),
            "newCharacterDescription": new_character.get("description")
        }
    except Exception as e:
        logging.error(f"[CREATE_CHARACTER_FROM_PROMPT] LLM error: {e}")
        raise HTTPException(status_code=500, detail={
            "error": "generation_failed",
            "message": "Ошибка генерации параметров персонажа",
            "code": "CHARACTER_GENERATION_FAILED"
        })
