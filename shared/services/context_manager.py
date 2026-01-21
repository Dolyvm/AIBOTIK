"""
Context Manager - Handles memory management, state parsing, and summarization
"""
import json
import logging
import re
from typing import Optional

from shared.services.llm import LLMClient
from shared.services.prompt_builder import build_character_prompt, build_world_prompt
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
    ) -> str:
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

        return clean_text

    async def _summarize_history(
        self,
        chat: Chat,
        history: list,
        character: Optional[dict] = None,
        world: Optional[dict] = None
    ):
        messages_to_summarize = history[:len(history) // 2]

        context_name = character["name"] if character else world["name"]

        summary_prompt = f"""You are summarizing a conversation between a user and {context_name}.

### EXISTING SUMMARY ###
{chat.summary if chat.summary else "This is the start of the conversation."}

### CURRENT EMOTIONAL STATE ###
Affinity: {chat.affinity}/100
Arousal: {chat.arousal}/100
Mood: {chat.current_mood}

### MESSAGES TO COMPRESS ###
{self._format_messages_for_summary(messages_to_summarize)}

### INSTRUCTIONS ###
Create a concise narrative summary that:
1. Preserves key facts, events, and revelations
2. Tracks the progression of the relationship
3. Notes important emotional moments
4. Integrates with the existing summary
5. Keeps it under 200 words

Write in Russian. Output ONLY the summary, no meta-commentary."""

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
