import json
import logging
import re
from datetime import datetime
from typing import Optional
from uuid import uuid4

from shared.services.llm import LLMClient
from shared.services.prompt_builder import build_character_prompt, build_world_prompt, build_player_prompt
from shared.services.cache import get_cache
from shared.services.redis_client import get_redis
from shared.config import (
    SUMMARY_THRESHOLD,
    MAX_HISTORY_LENGTH,
    LLM_MAX_TOKENS_CHARACTER,
    LLM_MAX_TOKENS_WORLD,
)
from shared.database import get_session
from shared.database.repositories import ChatRepository, MessageRepository, GeneratedImageRepository
from shared.models import Chat

class ContextManager:

    def __init__(self, llm_client: LLMClient, summary_threshold: int = None):
        self.llm = llm_client
        self.summary_threshold = summary_threshold or SUMMARY_THRESHOLD

    async def process_turn(
        self,
        chat: Chat,
        user_input: str,
        character: Optional[dict] = None,
        world: Optional[dict] = None,
        user_name: str = "User",
        allow_nsfw: bool = True
    ) -> dict:
        cache = get_cache()
        lock_name = f"chat:{chat.id}:processing"
        lock_acquired = False

        if cache:
            lock_acquired = await cache.acquire_lock(lock_name, ttl=120)
            if not lock_acquired:
                raise Exception("Chat is currently being processed. Please wait.")

        try:
            return await self._process_turn_internal(
                chat=chat,
                user_input=user_input,
                character=character,
                world=world,
                user_name=user_name,
                allow_nsfw=allow_nsfw
            )
        finally:
            if cache and lock_acquired:
                await cache.release_lock(lock_name)

    async def _process_turn_internal(
        self,
        chat: Chat,
        user_input: str,
        character: Optional[dict] = None,
        world: Optional[dict] = None,
        user_name: str = "User",
        allow_nsfw: bool = True
    ) -> dict:
        async with get_session() as session:
            message_repo = MessageRepository(session)
            chat_repo = ChatRepository(session)

            await message_repo.add(chat.id, "user", user_input)

            history_limit = min(chat.msgs_since_summary, MAX_HISTORY_LENGTH) if chat.summary else MAX_HISTORY_LENGTH
            messages = await message_repo.get_history(chat.id, limit=history_limit)
            history = [
                {"role": msg.role.value, "content": msg.content}
                for msg in messages
            ]

            if chat.msgs_since_summary >= self.summary_threshold:
                all_messages = await message_repo.get_history(chat.id, limit=chat.msgs_since_summary)
                full_history = [{"role": msg.role.value, "content": msg.content} for msg in all_messages]
                await self._summarize_history(chat, full_history, character, world, chat_repo)
                history = full_history[-5:] if len(full_history) > 5 else full_history

            if character:
                max_tokens = LLM_MAX_TOKENS_CHARACTER
                system_prompt = await build_character_prompt(
                    character=character,
                    chat=chat,
                    summary=chat.summary,
                    user_name=user_name,
                    allow_nsfw=allow_nsfw
                )
            elif world:
                max_tokens = LLM_MAX_TOKENS_WORLD
                system_prompt = await build_world_prompt(world, chat.summary, user_name, allow_nsfw)
            else:
                raise ValueError("Either character or world must be provided")

            response = await self.llm.generate(
                system_prompt=system_prompt,
                messages=history,
                max_tokens=max_tokens,
            )
            logging.info(f"{response=}")

            clean_text, state_updates = self._parse_meta(response)

            if state_updates:
                logging.info(f"{state_updates=}")
                updates = {}

                if "affinity_change" in state_updates:
                    new_affinity = max(0, min(100, chat.affinity + state_updates["affinity_change"]))
                    updates["affinity"] = new_affinity

                if "arousal_change" in state_updates:
                    new_arousal = max(0, min(100, chat.arousal + state_updates["arousal_change"]))
                    updates["arousal"] = new_arousal

                if "mood" in state_updates:
                    updates["current_mood"] = state_updates["mood"]

                if "new_location" in state_updates and state_updates["new_location"] is not None:
                    updates["current_location"] = state_updates["new_location"]
                meta_fields = {}
                if "thought" in state_updates:
                    meta_fields["thought"] = state_updates["thought"]
                if "new_action" in state_updates and state_updates["new_action"] is not None:
                    meta_fields["action"] = state_updates["new_action"]

                if meta_fields:
                    current_meta = chat.state_meta or {}
                    current_meta.update(meta_fields)
                    updates["state_meta"] = current_meta

                if updates:
                    logging.info(f"Updating chat metrics: {updates}")
                    await chat_repo.update_metrics(chat.id, updates)
                    for key, value in updates.items():
                        setattr(chat, key, value)

                    cache = get_cache()
                    if cache:
                        await cache.invalidate_chat_state(chat.id)

            await message_repo.add(chat.id, "assistant", clean_text)

            image_url = None
            nsfw_level = None
            image_task_id = None
            if state_updates.get("send_photo", False) and character is not None:
                msgs_since_photo = chat.msgs_since_summary - chat.last_auto_photo_at
                if msgs_since_photo >= 4:
                    logging.info(f"Triggering auto-photo generation (msgs_since_photo={msgs_since_photo})")
                    photo_result = await self._trigger_photo_generation(
                        chat, character, world, history, session, allow_nsfw
                    )
                    if photo_result:
                        if isinstance(photo_result, dict):
                            if "image_task_id" in photo_result:
                                image_task_id = photo_result.get("image_task_id")
                            else:
                                image_url = photo_result.get("url")
                                nsfw_level = photo_result.get("nsfw_level")
                        else:
                            image_url = photo_result
                        await chat_repo.update_metrics(
                            chat.id,
                            {"last_auto_photo_at": chat.msgs_since_summary}
                        )
                        chat.last_auto_photo_at = chat.msgs_since_summary
                else:
                    logging.info(f"Auto-photo skipped due to cooldown (msgs_since_photo={msgs_since_photo})")

        return {
            "text": clean_text,
            "image_url": image_url,
            "nsfw_level": nsfw_level,
            "image_task_id": image_task_id
        }

    async def _summarize_history(
        self,
        chat: Chat,
        history: list,
        character: Optional[dict] = None,
        world: Optional[dict] = None,
        chat_repo: Optional[ChatRepository] = None
    ):
        messages_to_summarize = history[:-5] if len(history) > 5 else history

        from shared.services.prompt_service import get_prompt

        context_name = character["name"] if character else world["name"]

        summary_prompt_template = await get_prompt("summary_prompt")
        summary_prompt = summary_prompt_template.format(
            context_name=context_name,
            existing_summary=chat.summary if chat.summary else "This is the start of the conversation.",
            affinity=chat.affinity,
            arousal=chat.arousal,
            mood=chat.current_mood,
            messages=self._format_messages_for_summary(messages_to_summarize)
        )

        summary = await self.llm.generate(
            system_prompt=summary_prompt,
            messages=[],
            max_tokens=400,
            temperature=0.3
        )

        if chat_repo:
            await chat_repo.update_metrics(
                chat.id,
                {
                    "summary": summary.strip(),
                    "msgs_since_summary": 0,
                    "last_auto_photo_at": 0
                }
            )
        else:
            async with get_session() as session:
                repo = ChatRepository(session)
                await repo.update_metrics(
                    chat.id,
                    {
                        "summary": summary.strip(),
                        "msgs_since_summary": 0,
                        "last_auto_photo_at": 0
                    }
                )

        chat.summary = summary.strip()
        chat.msgs_since_summary = 0
        chat.last_auto_photo_at = 0

    def _format_messages_for_summary(self, messages: list) -> str:
        formatted = []
        for msg in messages:
            role = "Пользователь" if msg["role"] == "user" else "Персонаж"
            formatted.append(f"{role}: {msg['content']}")
        return "\n".join(formatted)

    async def _trigger_photo_generation(
        self,
        chat: Chat,
        character: Optional[dict],
        world: Optional[dict],
        history: list,
        session=None,
        allow_nsfw: bool = True
    ) -> Optional[str]:
        try:
            import sys
            from pathlib import Path

            backend_path = Path(__file__).parent.parent.parent / "backend" / "api"
            if str(backend_path) not in sys.path:
                sys.path.insert(0, str(backend_path))

            from image_gen.schemas.generate import Prompt
            from image_gen.services.generate import submit_anime, submit_real
            from image_gen.services.scene_analyzer import (
                SceneAnalyzer,
                calculate_nsfw_fallback,
                calculate_sfw_fallback
            )
            from shared.config import SCENE_ANALYZER_ENABLED, SCENE_ANALYZER_MODEL

            content = character or world
            if not content:
                return None

            state_meta = chat.state_meta or {}
            nsfw_level = 0
            outfit_key = "default_outfit"
            environment = ""
            pose = ""

            if SCENE_ANALYZER_ENABLED and history:
                try:
                    scene_llm = LLMClient(model=SCENE_ANALYZER_MODEL)
                    analyzer = SceneAnalyzer(scene_llm)

                    visual = content.get("visual", {})
                    wardrobe = visual.get("wardrobe", {})
                    if not isinstance(wardrobe, dict):
                        wardrobe = {}
                    available_outfits = ["default_outfit"] + list(wardrobe.keys())

                    scene = await analyzer.analyze(
                        history=history,
                        character_name=content["name"],
                        available_outfits=available_outfits,
                        allow_nsfw=allow_nsfw,
                        chat_id=chat.id
                    )

                    nsfw_level = scene.nsfw_level
                    outfit_key = scene.outfit_key
                    pose = scene.pose
                    environment = scene.location

                    logging.info(f"Auto-photo scene analysis: {scene.reasoning}")

                except Exception as e:
                    logging.warning(f"Scene analysis failed for auto-photo, using fallback: {e}")
                    if allow_nsfw:
                        nsfw_level = calculate_nsfw_fallback(chat.arousal, chat.affinity)
                    else:
                        nsfw_level = calculate_sfw_fallback(chat.arousal, chat.affinity)
                    environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")
            else:
                if allow_nsfw:
                    nsfw_level = calculate_nsfw_fallback(chat.arousal, chat.affinity)
                else:
                    nsfw_level = calculate_sfw_fallback(chat.arousal, chat.affinity)
                environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")

            if not allow_nsfw:
                nsfw_level = min(nsfw_level, 1)

            environment = chat.current_location or environment

            prompt = Prompt.from_character(
                character=content,
                outfit_key=outfit_key,
                nsfw_level=nsfw_level,
                environment=environment,
            )

            prompt.action = state_meta.get("action") or pose
            pos, neg = await prompt.build_prompt(content.get("model_type"))

            logging.info(f"Auto-photo generation: {pos=}")

            model_type = content.get("model_type")
            if model_type not in ("anime", "real"):
                logging.warning(f"Unsupported model type for auto-photo: {model_type}")
                return None

            # Create task and enqueue for background processing
            task_id = str(uuid4())

            task_params = {
                "chat_id": chat.id,
                "user_id": chat.user_id,
                "model_type": model_type,
                "positive_prompt": pos,
                "negative_prompt": neg,
                "allow_nsfw": allow_nsfw,
                "nsfw_level": nsfw_level,
                "pose": pose,
            }

            # Store initial task status in Redis
            redis = await get_redis()
            await redis.set(
                f"task:{task_id}",
                json.dumps({
                    "status": "pending",
                    "chat_id": chat.id,
                    "created_at": datetime.utcnow().isoformat()
                }),
                ex=3600
            )

            # Try to enqueue task via arq
            try:
                from main import app
                arq_pool = getattr(app.state, "arq_pool", None)
                if arq_pool:
                    await arq_pool.enqueue_job("generate_image_task", task_id, task_params)
                    logging.info(f"Auto-photo task {task_id} enqueued for chat {chat.id}")
                    return {"image_task_id": task_id}
                else:
                    # Fallback: execute synchronously if arq not configured
                    logging.warning("arq pool not configured for auto-photo, executing synchronously")
                    from shared.queue.tasks import generate_image_task
                    ctx = {"redis": redis, "get_session": get_session}
                    result = await generate_image_task(ctx, task_id, task_params)
                    if result.get("status") == "completed":
                        return result.get("result", {})
                    return None
            except Exception as e:
                logging.error(f"Failed to enqueue auto-photo task: {e}")
                # Fallback to synchronous execution
                try:
                    from shared.queue.tasks import generate_image_task
                    ctx = {"redis": redis, "get_session": get_session}
                    result = await generate_image_task(ctx, task_id, task_params)
                    if result.get("status") == "completed":
                        return result.get("result", {})
                except Exception as inner_e:
                    logging.error(f"Fallback auto-photo generation also failed: {inner_e}")
                return None

        except Exception as e:
            logging.error(f"Auto-photo generation failed: {e}")
            return None

    def _parse_meta(self, response_text: str) -> tuple[str, dict]:
                                             
        meta_pattern = r'<meta>(.*?)</meta>'
        matches = re.findall(meta_pattern, response_text, re.DOTALL)

        state_updates = {}

        if matches:
            for match in matches:
                try:
                    updates = json.loads(match.strip().replace("*", "").replace("+", ""))
                    state_updates.update(updates)
                except json.JSONDecodeError:
                    logging.info("malformed json: ", match.strip().replace("\n", ""))
                                           
                    pass

        clean_text = re.sub(meta_pattern, '', response_text, flags=re.DOTALL).strip()

        return clean_text, state_updates

    async def auto_reply_cycle(
        self,
        chat: Chat,
        character: Optional[dict] = None,
        world: Optional[dict] = None,
        user_name: str = "User",
        allow_nsfw: bool = True,
        only_user_reply: bool = False
    ) -> dict:
        cache = get_cache()
        lock_name = f"chat:{chat.id}:auto_reply"
        lock_acquired = False

        if cache:
            lock_acquired = await cache.acquire_lock(lock_name, ttl=180)
            if not lock_acquired:
                raise Exception("Auto-reply already in progress for this chat.")

        try:
            return await self._auto_reply_cycle_internal(
                chat=chat,
                character=character,
                world=world,
                user_name=user_name,
                allow_nsfw=allow_nsfw,
                only_user_reply=only_user_reply
            )
        finally:
            if cache and lock_acquired:
                await cache.release_lock(lock_name)

    async def _auto_reply_cycle_internal(
        self,
        chat: Chat,
        character: Optional[dict] = None,
        world: Optional[dict] = None,
        user_name: str = "User",
        allow_nsfw: bool = True,
        only_user_reply: bool = False
    ) -> dict:
        async with get_session() as session:
            message_repo = MessageRepository(session)
            messages = await message_repo.get_history(chat.id, limit=MAX_HISTORY_LENGTH)

        history = [{"role": msg.role.value, "content": msg.content} for msg in messages]

        last_assistant_msg = next(
            (msg for msg in reversed(messages) if msg.role.value == 'assistant'),
            None
        )

        if not last_assistant_msg:
            if character:
                last_msg_content = character.get("scenario", "")
            else:
                last_msg_content = world.get("description", "")
        else:
            last_msg_content = last_assistant_msg.content

        char_name = character["name"] if character else world["name"]
        player_prompt = await build_player_prompt(
            character_name=char_name,
            last_character_message=last_msg_content,
            chat_history=history,
            user_name=user_name
        )

        player_action = await self.llm.generate(
            system_prompt=player_prompt,
            messages=[],
            max_tokens=100,
            temperature=0.9
        )

        if only_user_reply:
            return {
                "player_message": player_action.strip()
            }

        result = await self.process_turn(
            chat=chat,
            user_input=player_action.strip(),
            character=character,
            world=world,
            user_name=user_name,
            allow_nsfw=allow_nsfw
        )

        return {
            "player_message": player_action.strip(),
            "character_response": result["text"],
            "image_url": result.get("image_url"),
            "nsfw_level": result.get("nsfw_level"),
            "image_task_id": result.get("image_task_id"),
            "affinity": chat.affinity,
            "arousal": chat.arousal
        }
