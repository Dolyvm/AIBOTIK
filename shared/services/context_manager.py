"""
Context Manager - Handles memory management, state parsing, and summarization
"""
import json
import logging
import re
from typing import Optional

from shared.services.llm import LLMClient
from shared.services.prompt_builder import build_character_prompt, build_world_prompt, build_player_prompt
from shared.config import (
    SUMMARY_THRESHOLD,
    MAX_HISTORY_LENGTH,
    LLM_MAX_TOKENS_CHARACTER,
    LLM_MAX_TOKENS_WORLD,
)
from shared import repository
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
        user_name: str = "User"
    ) -> dict:
        await repository.add_message(chat.id, "user", user_input)

        messages = await repository.get_chat_history(chat.id, limit=MAX_HISTORY_LENGTH)
        history = [
            {"role": msg.role.value, "content": msg.content}
            for msg in messages
        ]

        if chat.msgs_since_summary >= self.summary_threshold and len(history) > MAX_HISTORY_LENGTH:
            await self._summarize_history(chat, history, character, world)

        if character:
            max_tokens = LLM_MAX_TOKENS_CHARACTER
            system_prompt = build_character_prompt(
                character=character,
                chat=chat,
                summary=chat.summary,
                user_name=user_name
            )
        elif world:
            max_tokens = LLM_MAX_TOKENS_WORLD
            system_prompt = build_world_prompt(world, chat.summary, user_name)
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
                await repository.update_chat_metrics(chat.id, updates)
                for key, value in updates.items():
                    setattr(chat, key, value)
        await repository.add_message(chat.id, "assistant", clean_text)

        image_url = None
        if state_updates.get("send_photo", False):
            msgs_since_photo = chat.msgs_since_summary - chat.last_auto_photo_at
            if msgs_since_photo >= 4:
                logging.info(f"Triggering auto-photo generation (msgs_since_photo={msgs_since_photo})")
                image_url = await self._trigger_photo_generation(chat, character, world, history)
                if image_url:
                    await repository.update_chat_metrics(
                        chat.id,
                        {"last_auto_photo_at": chat.msgs_since_summary}
                    )
                    chat.last_auto_photo_at = chat.msgs_since_summary
            else:
                logging.info(f"Auto-photo skipped due to cooldown (msgs_since_photo={msgs_since_photo})")

        return {"text": clean_text, "image_url": image_url}

    async def _summarize_history(
        self,
        chat: Chat,
        history: list,
        character: Optional[dict] = None,
        world: Optional[dict] = None
    ):
        messages_to_summarize = history[:len(history) // 2]

        from shared.services.prompt_service import get_prompt

        context_name = character["name"] if character else world["name"]

        summary_prompt_template = get_prompt("summary_prompt")
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

        await repository.update_chat_metrics(
            chat.id,
            {
                "summary": summary.strip(),
                "msgs_since_summary": 0
            }
        )
        chat.summary = summary.strip()
        chat.msgs_since_summary = 0

    def _format_messages_for_summary(self, messages: list) -> str:
        """Format messages for summarization prompt."""
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
        history: list
    ) -> Optional[str]:
        try:
            import sys
            from pathlib import Path

            # Add webapp to path if not already there
            webapp_path = Path(__file__).parent.parent.parent / "webapp" / "api"
            if str(webapp_path) not in sys.path:
                sys.path.insert(0, str(webapp_path))

            from image_gen.schemas.generate import Prompt
            from image_gen.services.generate import submit_anime, submit_real
            from image_gen.services.scene_analyzer import SceneAnalyzer, calculate_nsfw_fallback
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
                        available_outfits=available_outfits
                    )

                    nsfw_level = scene.nsfw_level
                    outfit_key = scene.outfit_key
                    pose = scene.pose
                    environment = scene.location

                    logging.info(f"Auto-photo scene analysis: {scene.reasoning}")

                except Exception as e:
                    logging.warning(f"Scene analysis failed for auto-photo, using fallback: {e}")
                    nsfw_level = calculate_nsfw_fallback(chat.arousal, chat.affinity)
                    environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")
            else:
                nsfw_level = calculate_nsfw_fallback(chat.arousal, chat.affinity)
                environment = ", ".join(content.get("tags", [])).replace("NSFW, ", "")

            environment = chat.current_location or environment

            prompt = Prompt.from_character(
                character=content,
                outfit_key=outfit_key,
                nsfw_level=nsfw_level,
                environment=environment,
            )

            prompt.action = state_meta.get("action") or pose
            pos, neg = prompt.build_prompt(content.get("model_type"))

            logging.info(f"Auto-photo generation: {pos=}")

            image_url = None
            if content.get("model_type") == "anime":
                image_url = await submit_anime(pos, neg)
            elif content.get("model_type") == "real":
                image_url = await submit_real(prompt=pos, allow_nsfw=True, nsfw_level=nsfw_level)

            if image_url:
                try:
                    # Add webapp to path for image_storage
                    webapp_services_path = Path(__file__).parent.parent.parent / "webapp"
                    if str(webapp_services_path) not in sys.path:
                        sys.path.insert(0, str(webapp_services_path))

                    from services.image_storage import download_and_save_image, get_public_url, ImageStorageError

                    local_path = None
                    file_size = None
                    content_type = None
                    public_url = image_url

                    try:
                        local_path, file_size, content_type = await download_and_save_image(
                            provider_url=image_url,
                            user_id=chat.user_id
                        )
                        public_url = get_public_url(local_path)
                        logging.info(f"Auto-photo saved locally: {local_path}")
                    except ImageStorageError as e:
                        logging.warning(f"Failed to save auto-photo locally, using provider URL: {e}")

                    await repository.save_generated_image(
                        user_id=chat.user_id,
                        chat_id=chat.id,
                        prompt=pos,
                        provider_url=image_url,
                        local_path=local_path,
                        file_size=file_size,
                        content_type=content_type
                    )

                    return public_url

                except Exception as e:
                    logging.error(f"Failed to save auto-generated image: {e}")
                    return image_url

            return None

        except Exception as e:
            logging.error(f"Auto-photo generation failed: {e}")
            return None

    def _parse_meta(self, response_text: str) -> tuple[str, dict]:
        """
        Parse metadata tags from LLM response.

        Args:
            response_text: Raw LLM response

        Returns:
            Tuple of (clean_text, state_updates_dict)
        """
        # Regex to find <meta>...</meta> tags
        meta_pattern = r'<meta>(.*?)</meta>'
        matches = re.findall(meta_pattern, response_text, re.DOTALL)

        state_updates = {}

        if matches:
            for match in matches:
                try:
                    updates = json.loads(match.strip().replace("*", ""))
                    state_updates.update(updates)
                except json.JSONDecodeError:
                    logging.info("malformed json: ", match.strip().replace("\n", ""))
                    # Ignore malformed JSON
                    pass

        # Remove meta tags from response
        clean_text = re.sub(meta_pattern, '', response_text, flags=re.DOTALL).strip()

        return clean_text, state_updates
    
    async def auto_reply_cycle(
        self,
        chat: Chat,
        character: Optional[dict] = None,
        world: Optional[dict] = None,
        user_name: str = "User"
    ) -> dict:
        
        messages = await repository.get_chat_history(chat.id, limit=MAX_HISTORY_LENGTH)
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
        player_prompt = build_player_prompt(
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

        result = await self.process_turn(
            chat=chat,
            user_input=player_action.strip(),
            character=character,
            world=world,
            user_name=user_name
        )

        return {
            "player_message": player_action.strip(),
            "character_response": result["text"],
            "image_url": result.get("image_url"),
            "affinity": chat.affinity,
            "arousal": chat.arousal
        }