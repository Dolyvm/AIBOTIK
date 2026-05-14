import json
import logging
import re
from typing import Optional, Sequence

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
from shared.constants import get_heat_context, get_heat_level

logger = logging.getLogger(__name__)

PLAYER_AUTO_MESSAGE_SYSTEM_PROMPT = (
    "Ты генерируешь только одно следующее сообщение игрока для интерактивного "
    "романа. Ответ должен быть от первого лица игрока на русском языке, без "
    "JSON, meta, заголовков, role labels, пояснений и текста персонажа."
)
PLAYER_AUTO_MESSAGE_RETRY_INSTRUCTION = """
ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ ОТКЛОНЁН: {reason}

Отклонённый текст:
{bad_response}

Сгенерируй новый короткий ответ игрока от первого лица на русском.
Запрещено повторять прошлые сообщения игрока дословно, писать за персонажа,
использовать <meta>, JSON, markdown или role labels.
"""
PLAYER_AUTO_MESSAGE_FALLBACKS = (
    "Я задерживаю взгляд и тихо отвечаю: «Продолжай.»",
    "Я делаю короткий вдох и говорю: «Я слушаю.»",
    "Я чуть наклоняюсь ближе и внимательно жду продолжения.",
)

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


def _normalize_player_message_for_compare(content: str) -> str:
    text = _clean_generated_player_message(content)
    text = text.casefold().replace("ё", "е")
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def _invalid_player_message_reason(
    content: str,
    recent_user_messages: Optional[Sequence[str]] = None,
) -> Optional[str]:
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

    if recent_user_messages:
        normalized = _normalize_player_message_for_compare(text)
        if normalized:
            for previous in recent_user_messages:
                if normalized == _normalize_player_message_for_compare(previous):
                    return "duplicate_user_message"

    return None


def _prepare_generated_player_message(
    content: str,
    recent_user_messages: Optional[Sequence[str]] = None,
) -> tuple[str, Optional[str]]:
    text = _clean_generated_player_message(content)
    return text, _invalid_player_message_reason(text, recent_user_messages)


def _build_player_retry_prompt(
    player_prompt: str,
    bad_response: str,
    reason: str,
    recent_user_messages: Optional[Sequence[str]] = None,
    last_character_message: Optional[str] = None,
) -> str:
    context = (last_character_message or player_prompt or "").strip()
    previous = "\n".join(f"- {msg}" for msg in (recent_user_messages or [])[-5:])
    if not previous:
        previous = "Нет."
    rejection_instruction = PLAYER_AUTO_MESSAGE_RETRY_INSTRUCTION.format(
        reason=reason,
        bad_response=(bad_response or "<empty>")[:500],
    ).strip()

    return (
        f"{rejection_instruction}\n\n"
        f"Последняя реплика/действие персонажа:\n\"{context[:1500]}\"\n\n"
        f"Прошлые сообщения игрока, которые нельзя повторять дословно:\n{previous}\n\n"
        "Верни только финальный текст: 1-2 коротких предложения или действие игрока."
    )


def _fallback_player_message(recent_user_messages: Optional[Sequence[str]] = None) -> str:
    for candidate in PLAYER_AUTO_MESSAGE_FALLBACKS:
        _, reason = _prepare_generated_player_message(candidate, recent_user_messages)
        if not reason:
            return candidate
    return "Я молча киваю."


def _build_chat_updates_from_meta(chat: Chat, state_updates: dict) -> dict:
    updates = {}
    state_updates = dict(state_updates or {})
    state_updates.pop("affinity_change", None)
    state_updates.pop("arousal_change", None)

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
        current_meta = dict(chat.state_meta or {})
        current_meta.update(meta_fields)
        updates["state_meta"] = current_meta

    return updates


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
                updates = _build_chat_updates_from_meta(chat, state_updates)

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
            heat_level=get_heat_level(chat),
            heat_context=get_heat_context(get_heat_level(chat)),
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

        recent_user_messages = [
            msg.content
            for msg in messages
            if msg.role.value == "user"
        ][-5:]
        player_action = await self._generate_player_action(
            player_prompt,
            recent_user_messages=recent_user_messages,
            last_character_message=last_msg_content,
        )

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

    async def _generate_player_action(
        self,
        player_prompt: str,
        recent_user_messages: Optional[Sequence[str]] = None,
        last_character_message: Optional[str] = None,
    ) -> str:
        player_response = await self.player_llm.generate(
            system_prompt=PLAYER_AUTO_MESSAGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": player_prompt}],
            max_tokens=100,
            temperature=0.7
        )
        player_action, reason = _prepare_generated_player_message(
            player_response.content,
            recent_user_messages,
        )
        if not reason:
            logger.info("Accepted generated player auto-message: sample=%r", player_action[:300])
            return player_action

        logger.warning(
            "Rejected generated player auto-message: reason=%s sample=%r",
            reason,
            (player_response.content or "")[:300],
        )

        retry_prompt = _build_player_retry_prompt(
            player_prompt=player_prompt,
            bad_response=player_response.content or "",
            reason=reason,
            recent_user_messages=recent_user_messages,
            last_character_message=last_character_message,
        )
        retry_response = await self.player_llm.generate(
            system_prompt=PLAYER_AUTO_MESSAGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": retry_prompt}],
            max_tokens=80,
            temperature=0.4
        )
        player_action, retry_reason = _prepare_generated_player_message(
            retry_response.content,
            recent_user_messages,
        )
        if not retry_reason:
            logger.info("Accepted retry player auto-message: sample=%r", player_action[:300])
            return player_action

        logger.error(
            "Rejected retry player auto-message, using fallback: reason=%s sample=%r",
            retry_reason,
            (retry_response.content or "")[:300],
        )
        fallback = _fallback_player_message(recent_user_messages)
        logger.info("Using fallback player auto-message: sample=%r", fallback[:300])
        return fallback
