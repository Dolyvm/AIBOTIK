import json
import logging
import re
from typing import Optional

from shared.services.llm import LLMClient, LLMError, LLMResponse
from shared.services.prompt_builder import build_character_prompt, build_world_prompt, build_player_prompt
from shared.services.cache import get_cache
from shared.config import (
    SUMMARY_THRESHOLD,
    MAX_HISTORY_LENGTH,
    LLM_MAX_TOKENS_CHARACTER,
    LLM_MAX_TOKENS_WORLD,
    SUMMARY_MODEL,
    PLAYER_MODEL,
)
from shared.database import get_session
from shared.database.repositories import ChatRepository, MessageRepository
from shared.models import Chat

logger = logging.getLogger(__name__)

PLAYER_AUTO_MESSAGE_SYSTEM_PROMPT = (
    "Ты генерируешь только одно следующее сообщение игрока для интерактивного "
    "романа. Ответ должен быть от первого лица игрока на русском языке, без "
    "JSON, meta, заголовков, role labels, пояснений и текста персонажа."
)
PLAYER_AUTO_MESSAGE_RETRY_INSTRUCTION = """
ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ ОТКЛОНЁН:
{bad_response}

Исправь ошибку. Верни только одну короткую реплику или действие игрока от первого лица.
Запрещено писать за персонажа, использовать "он/она сказала", <meta>, JSON, markdown или role labels.
"""
PLAYER_AUTO_MESSAGE_FALLBACK = "Я смотрю внимательнее и тихо отвечаю: «Я слушаю.»"

_PLAYER_ROLE_LABEL_RE = re.compile(
    r"(?im)^\s*(?:system|assistant|developer|user|player|персонаж|игрок|"
    r"ассистент|пользователь|роль|контекст|инструкции|задача)\s*[:#]"
)
_PLAYER_LEADING_LABEL_RE = re.compile(
    r"(?i)^\s*(?:игрок|player|user|пользователь)\s*[:：-]\s*"
)
_CHARACTER_ATTRIBUTION_RE = re.compile(
    r"\b(?:сказал|сказала|ответил|ответила|произн[её]с|произнесла|"
    r"прошептал|прошептала|проговорил|проговорила|усмехнулся|усмехнулась|"
    r"улыбнулся|улыбнулась|вздохнул|вздохнула|кивнул|кивнула)\s+(?:он|она)\b"
    r"|\b(?:он|она)\s+(?:сказал|сказала|ответил|ответила|произн[её]с|"
    r"произнесла|прошептал|прошептала|проговорил|проговорила|усмехнулся|"
    r"усмехнулась|улыбнулся|улыбнулась|вздохнул|вздохнула|кивнул|кивнула)\b",
    re.IGNORECASE,
)
_PLAYER_SYSTEM_MARKERS = (
    "###",
    "<meta",
    "</meta",
    "system prompt",
    "developer message",
    "системный протокол",
    "системное сообщение",
    "инструкции",
    "роль",
    "контекст",
    "задача",
)


def _clean_generated_player_message(content: str) -> str:
    text = (content or "").strip()
    text = re.sub(r"```(?:[a-zA-Z0-9_-]+)?\s*", "", text)
    text = text.replace("```", "")
    text = re.sub(r"(?is)<meta\b[^>]*>.*?</meta>\s*", "", text)
    text = _PLAYER_LEADING_LABEL_RE.sub("", text).strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(" \n\t\"'")


def _invalid_player_message_reason(content: str) -> Optional[str]:
    text = (content or "").strip()
    if not text:
        return "empty"

    if len(text) > 700:
        return "too_long"

    if text.count("\n\n") > 2:
        return "too_many_paragraphs"

    if text[:1] in ("{", "["):
        return "structured_output"

    if _PLAYER_ROLE_LABEL_RE.search(text):
        return "role_label"

    lowered = text.casefold()
    for marker in _PLAYER_SYSTEM_MARKERS:
        if marker in lowered:
            return "system_marker"

    if _CHARACTER_ATTRIBUTION_RE.search(text):
        return "character_attribution"

    return None


def _prepare_generated_player_message(content: str) -> tuple[str, Optional[str]]:
    text = _clean_generated_player_message(content)
    return text, _invalid_player_message_reason(text)


class ContextManager:

    def __init__(self, llm_client: LLMClient, summary_threshold: int = None):
        self.llm = llm_client
        self.summary_llm = LLMClient(
            model=SUMMARY_MODEL,
            provider={"sort": "throughput"},
            reasoning={"enabled": False},
        )
        self.player_llm = LLMClient(
            model=PLAYER_MODEL,
            provider={"sort": "throughput"},
            reasoning={"enabled": False},
        )
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

            history_limit = MAX_HISTORY_LENGTH
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
                system_prompt = await build_world_prompt(
                    world,
                    chat.summary,
                    user_name,
                    allow_nsfw,
                    location=chat.current_location or "",
                    scenario_index=chat.scenario_index or 0,
                )
            else:
                raise ValueError("Either character or world must be provided")

            response = await self._generate_complete_story_response(
                system_prompt=system_prompt,
                messages=history,
                max_tokens=max_tokens,
                chat_id=chat.id,
            )
            logging.info(f"response={response.content}")

            clean_text, state_updates = self._parse_meta(response.content)

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

            await message_repo.add(
                chat.id,
                "assistant",
                clean_text,
                tokens_used=response.completion_tokens,
            )

        return {
            "text": clean_text,
        }

    async def _generate_complete_story_response(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int,
        chat_id: int,
    ) -> LLMResponse:
        response = await self.llm.generate(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
        )

        if response.finish_reason != "length":
            return response

        trimmed_content = self._trim_to_complete_sentence(response.content)
        if trimmed_content:
            logging.error(
                "LLM response hit length for chat_id=%s; saving complete sentences only. id=%s",
                chat_id,
                response.id,
            )
            response.content = trimmed_content
            return response

        logging.error(
            "LLM response truncated and could not be trimmed for chat_id=%s id=%s",
            chat_id,
            response.id,
        )
        raise LLMError("LLM response was truncated; assistant response was not saved")

    def _trim_to_complete_sentence(self, text: str) -> str:
        if not text:
            return ""

        meta_match = re.match(r'\s*<meta>\s*.*?\s*</meta>\s*', text, re.DOTALL)
        if not meta_match:
            return ""

        prefix = text[:meta_match.end()]
        body = text[meta_match.end():].strip()
        if not body:
            return ""

        last_sentence_end = max(body.rfind(mark) for mark in (".", "!", "?", "…"))
        if last_sentence_end < 200:
            return ""

        return f"{prefix}{body[:last_sentence_end + 1].strip()}"

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
            location=chat.current_location or "не определена",
            messages=self._format_messages_for_summary(messages_to_summarize)
        )

        summary_response = await self.summary_llm.generate(
            system_prompt=summary_prompt,
            messages=[],
            max_tokens=600,
            temperature=0.3
        )
        summary = summary_response.content.strip()

        if chat_repo:
            await chat_repo.update_metrics(
                chat.id,
                {
                    "summary": summary,
                    "msgs_since_summary": 0,
                }
            )
        else:
            async with get_session() as session:
                repo = ChatRepository(session)
                await repo.update_metrics(
                    chat.id,
                    {
                        "summary": summary,
                        "msgs_since_summary": 0,
                    }
                )

        chat.summary = summary
        chat.msgs_since_summary = 0

    def _format_messages_for_summary(self, messages: list) -> str:
        formatted = []
        for msg in messages:
            role = "Пользователь" if msg["role"] == "user" else "Персонаж"
            formatted.append(f"{role}: {msg['content']}")
        return "\n".join(formatted)

    def _parse_meta(self, response_text: str) -> tuple[str, dict]:
        state_updates = {}

        if not response_text:
            return "", state_updates

        meta_match = re.match(r'\s*<meta>\s*(.*?)\s*</meta>\s*', response_text, re.DOTALL)
        if not meta_match:
            return response_text.strip(), state_updates

        raw_meta = meta_match.group(1).strip()
        try:
            normalized_meta = raw_meta.replace("*", "")
            normalized_meta = re.sub(r'(:\s*)\+(\d+)', r'\1\2', normalized_meta)
            updates = json.loads(normalized_meta)
            if isinstance(updates, dict):
                state_updates.update(updates)
        except json.JSONDecodeError:
            logging.warning("Malformed LLM meta JSON: %s", raw_meta.replace("\n", " ")[:500])

        clean_text = response_text[meta_match.end():].strip()

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

        player_action = await self._generate_player_action(player_prompt)

        if only_user_reply:
            return {
                "player_message": player_action
            }

        result = await self.process_turn(
            chat=chat,
            user_input=player_action,
            character=character,
            world=world,
            user_name=user_name,
            allow_nsfw=allow_nsfw
        )

        return {
            "player_message": player_action,
            "character_response": result["text"],
            "affinity": chat.affinity,
            "arousal": chat.arousal
        }

    async def _generate_player_action(self, player_prompt: str) -> str:
        player_response = await self.player_llm.generate(
            system_prompt=PLAYER_AUTO_MESSAGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": player_prompt}],
            max_tokens=100,
            temperature=0.7
        )
        player_action, reason = _prepare_generated_player_message(player_response.content)
        if not reason:
            return player_action

        logger.warning(
            "Rejected generated player auto-message: reason=%s sample=%r",
            reason,
            (player_response.content or "")[:300],
        )

        retry_prompt = (
            f"{player_prompt.rstrip()}\n\n"
            f"{PLAYER_AUTO_MESSAGE_RETRY_INSTRUCTION.format(bad_response=(player_response.content or '')[:500]).strip()}"
        )
        retry_response = await self.player_llm.generate(
            system_prompt=PLAYER_AUTO_MESSAGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": retry_prompt}],
            max_tokens=80,
            temperature=0.4
        )
        player_action, retry_reason = _prepare_generated_player_message(retry_response.content)
        if not retry_reason:
            return player_action

        logger.error(
            "Rejected retry player auto-message, using fallback: reason=%s sample=%r",
            retry_reason,
            (retry_response.content or "")[:300],
        )
        return PLAYER_AUTO_MESSAGE_FALLBACK
