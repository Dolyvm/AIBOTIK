import json
import logging
from typing import Optional, Any
from redis import asyncio as aioredis

logger = logging.getLogger(__name__)

TTL_USER = 300  
TTL_CHAT_OWNER = 3600  
TTL_CHARACTER = 3600  
TTL_WORLD = 3600  
TTL_CHARACTERS_LIST = 1800  
TTL_WORLDS_LIST = 1800  
TTL_PROMPT = 86400  
TTL_CHARACTER_MODIFIERS = 86400  
TTL_NSFW_LEVELS = 86400  
TTL_CHAT_STATE = 10800  
TTL_ACTIVE_CHAT = 10800  
TTL_FILTERS = 3600  
TTL_SCENE_ANALYSIS = 300  

class CacheService:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
    async def get_user(self, telegram_id: int) -> Optional[dict]:
        key = f"user:{telegram_id}"
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting user {telegram_id}: {e}")
            return None

    async def set_user(self, telegram_id: int, user_data: dict) -> None:
        key = f"user:{telegram_id}"
        try:
            await self.redis.setex(key, TTL_USER, json.dumps(user_data))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting user {telegram_id}: {e}")

    async def invalidate_user(self, telegram_id: int) -> None:
        key = f"user:{telegram_id}"
        try:
            await self.redis.delete(key)
            logger.debug(f"Cache INVALIDATED: {key}")
        except Exception as e:
            logger.error(f"Cache error invalidating user {telegram_id}: {e}")

    async def get_chat_owner(self, chat_id: int) -> Optional[int]:
        key = f"chat:{chat_id}:owner"
        try:
            owner = await self.redis.get(key)
            if owner:
                logger.debug(f"Cache HIT: {key}")
                return int(owner)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting chat owner {chat_id}: {e}")
            return None

    async def set_chat_owner(self, chat_id: int, telegram_id: int) -> None:
        key = f"chat:{chat_id}:owner"
        try:
            await self.redis.setex(key, TTL_CHAT_OWNER, str(telegram_id))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting chat owner {chat_id}: {e}")

    async def get_character(self, character_id: str) -> Optional[dict]:
        key = f"character:{character_id}"
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting character {character_id}: {e}")
            return None

    async def set_character(self, character_id: str, data: dict) -> None:
        key = f"character:{character_id}"
        try:
            await self.redis.setex(key, TTL_CHARACTER, json.dumps(data))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting character {character_id}: {e}")

    async def invalidate_character(self, character_id: str) -> None:
        try:
            await self.redis.delete(f"character:{character_id}")
            await self.redis.delete("characters:all")
            keys = await self.redis.keys("characters:tag:*")
            if keys:
                await self.redis.delete(*keys)
            await self.redis.delete("filters:characters:tags")
            await self.redis.delete("filters:characters:styles")
            logger.debug(f"Cache INVALIDATED: character:{character_id} and related lists")
        except Exception as e:
            logger.error(f"Cache error invalidating character {character_id}: {e}")

    async def get_all_characters(self) -> Optional[list]:
        key = "characters:all"
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting all characters: {e}")
            return None

    async def set_all_characters(self, characters: list) -> None:
        key = "characters:all"
        try:
            await self.redis.setex(key, TTL_CHARACTERS_LIST, json.dumps(characters))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting all characters: {e}")

    async def get_world(self, world_id: str) -> Optional[dict]:
        key = f"world:{world_id}"
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting world {world_id}: {e}")
            return None

    async def set_world(self, world_id: str, data: dict) -> None:
        key = f"world:{world_id}"
        try:
            await self.redis.setex(key, TTL_WORLD, json.dumps(data))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting world {world_id}: {e}")

    async def invalidate_world(self, world_id: str) -> None:
        try:
            await self.redis.delete(f"world:{world_id}")
            await self.redis.delete("worlds:all")
            keys = await self.redis.keys("worlds:tag:*")
            if keys:
                await self.redis.delete(*keys)
            await self.redis.delete("filters:worlds:tags")
            logger.debug(f"Cache INVALIDATED: world:{world_id} and related lists")
        except Exception as e:
            logger.error(f"Cache error invalidating world {world_id}: {e}")

    async def get_all_worlds(self) -> Optional[list]:
        key = "worlds:all"
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting all worlds: {e}")
            return None

    async def set_all_worlds(self, worlds: list) -> None:
        key = "worlds:all"
        try:
            await self.redis.setex(key, TTL_WORLDS_LIST, json.dumps(worlds))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting all worlds: {e}")

    async def get_prompt(self, key: str) -> Optional[str]:
        cache_key = f"prompt:{key}"
        try:
            data = await self.redis.get(cache_key)
            if data:
                logger.debug(f"Cache HIT: {cache_key}")
                return data
            logger.debug(f"Cache MISS: {cache_key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting prompt {key}: {e}")
            return None

    async def set_prompt(self, key: str, content: str) -> None:
        cache_key = f"prompt:{key}"
        try:
            await self.redis.setex(cache_key, TTL_PROMPT, content)
            logger.debug(f"Cache SET: {cache_key}")
        except Exception as e:
            logger.error(f"Cache error setting prompt {key}: {e}")

    async def invalidate_prompt(self, key: str) -> None:
        cache_key = f"prompt:{key}"
        try:
            await self.redis.delete(cache_key)
            logger.debug(f"Cache INVALIDATED: {cache_key}")
        except Exception as e:
            logger.error(f"Cache error invalidating prompt {key}: {e}")

    async def invalidate_all_prompts(self) -> None:
        try:
            keys = await self.redis.keys("prompt:*")
            if keys:
                await self.redis.delete(*keys)
            logger.debug("Cache INVALIDATED: all prompts")
        except Exception as e:
            logger.error(f"Cache error invalidating all prompts: {e}")

    async def get_character_modifiers(self, character_id: str) -> Optional[dict]:
        key = f"character_modifiers:{character_id}"
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting character modifiers {character_id}: {e}")
            return None

    async def set_character_modifiers(self, character_id: str, modifiers: dict) -> None:
        key = f"character_modifiers:{character_id}"
        try:
            await self.redis.setex(key, TTL_CHARACTER_MODIFIERS, json.dumps(modifiers))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting character modifiers {character_id}: {e}")

    async def invalidate_character_modifiers(self) -> None:
        try:
            keys = await self.redis.keys("character_modifiers:*")
            if keys:
                await self.redis.delete(*keys)
            logger.debug("Cache INVALIDATED: all character modifiers")
        except Exception as e:
            logger.error(f"Cache error invalidating character modifiers: {e}")

    async def get_nsfw_levels(self) -> Optional[list]:
        key = "nsfw_levels"
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting nsfw levels: {e}")
            return None

    async def set_nsfw_levels(self, levels: list) -> None:
        key = "nsfw_levels"
        try:
            await self.redis.setex(key, TTL_NSFW_LEVELS, json.dumps(levels))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting nsfw levels: {e}")

    async def invalidate_nsfw_levels(self) -> None:
        try:
            await self.redis.delete("nsfw_levels")
            logger.debug("Cache INVALIDATED: nsfw_levels")
        except Exception as e:
            logger.error(f"Cache error invalidating nsfw levels: {e}")

    async def get_chat_state(self, chat_id: int) -> Optional[dict]:
        key = f"chat:{chat_id}:state"
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting chat state {chat_id}: {e}")
            return None

    async def set_chat_state(self, chat_id: int, state: dict) -> None:
        key = f"chat:{chat_id}:state"
        try:
            await self.redis.setex(key, TTL_CHAT_STATE, json.dumps(state))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting chat state {chat_id}: {e}")

    async def invalidate_chat_state(self, chat_id: int) -> None:
        key = f"chat:{chat_id}:state"
        try:
            await self.redis.delete(key)
            logger.debug(f"Cache INVALIDATED: {key}")
        except Exception as e:
            logger.error(f"Cache error invalidating chat state {chat_id}: {e}")

    async def get_active_chat(self, telegram_id: int) -> Optional[int]:
        key = f"user:{telegram_id}:active_chat"
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT: {key}")
                return int(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting active chat {telegram_id}: {e}")
            return None

    async def set_active_chat(self, telegram_id: int, chat_id: int) -> None:
        key = f"user:{telegram_id}:active_chat"
        try:
            await self.redis.setex(key, TTL_ACTIVE_CHAT, str(chat_id))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting active chat {telegram_id}: {e}")

    async def invalidate_active_chat(self, telegram_id: int) -> None:
        key = f"user:{telegram_id}:active_chat"
        try:
            await self.redis.delete(key)
            logger.debug(f"Cache INVALIDATED: {key}")
        except Exception as e:
            logger.error(f"Cache error invalidating active chat {telegram_id}: {e}")

    async def get_character_filters(self) -> Optional[dict]:
        try:
            tags = await self.redis.get("filters:characters:tags")
            styles = await self.redis.get("filters:characters:styles")
            if tags and styles:
                logger.debug("Cache HIT: character filters")
                return {
                    "tags": json.loads(tags),
                    "styles": json.loads(styles)
                }
            logger.debug("Cache MISS: character filters")
            return None
        except Exception as e:
            logger.error(f"Cache error getting character filters: {e}")
            return None

    async def set_character_filters(self, tags: list, styles: list) -> None:
        try:
            await self.redis.setex("filters:characters:tags", TTL_FILTERS, json.dumps(tags))
            await self.redis.setex("filters:characters:styles", TTL_FILTERS, json.dumps(styles))
            logger.debug("Cache SET: character filters")
        except Exception as e:
            logger.error(f"Cache error setting character filters: {e}")

    async def get_scene_analysis(self, chat_id: int, context_hash: str) -> Optional[dict]:
        key = f"scene:chat:{chat_id}:{context_hash}"
        try:
            data = await self.redis.get(key)
            if data:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(data)
            logger.debug(f"Cache MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Cache error getting scene analysis {chat_id}: {e}")
            return None

    async def set_scene_analysis(self, chat_id: int, context_hash: str, analysis: dict) -> None:
        key = f"scene:chat:{chat_id}:{context_hash}"
        try:
            await self.redis.setex(key, TTL_SCENE_ANALYSIS, json.dumps(analysis))
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Cache error setting scene analysis {chat_id}: {e}")

    async def acquire_lock(self, lock_name: str, ttl: int = 60) -> bool:
        key = f"lock:{lock_name}"
        try:
            result = await self.redis.set(key, "1", nx=True, ex=ttl)
            if result:
                logger.debug(f"Lock ACQUIRED: {key}")
                return True
            logger.debug(f"Lock DENIED (already locked): {key}")
            return False
        except Exception as e:
            logger.error(f"Lock error acquiring {lock_name}: {e}")
            return False

    async def release_lock(self, lock_name: str) -> None:
        key = f"lock:{lock_name}"
        try:
            await self.redis.delete(key)
            logger.debug(f"Lock RELEASED: {key}")
        except Exception as e:
            logger.error(f"Lock error releasing {lock_name}: {e}")

_cache_service: Optional[CacheService] = None

def get_cache() -> Optional[CacheService]:
    return _cache_service

def set_cache(cache: CacheService) -> None:
    global _cache_service
    _cache_service = cache
