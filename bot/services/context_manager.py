"""
Context Manager - Handles memory management, state parsing, and summarization
"""
import json
import re
from typing import Tuple, Optional
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.llm import LLMClient
from services.prompt_builder import build_character_prompt, build_world_prompt
from shared.card_parser import get_character


class ContextManager:
    """Manages conversation context, state, and memory for chats"""

    def __init__(self, llm_client: LLMClient, summary_threshold: int = 15):
        """
        Initialize ContextManager.

        Args:
            llm_client: LLM client for generating responses and summaries
            summary_threshold: Number of messages before triggering summarization
        """
        self.llm = llm_client
        self.summary_threshold = summary_threshold

    async def process_turn(
        self,
        chat,
        user_input: str,
        character: Optional[dict] = None,
        world: Optional[dict] = None,
        user_name: str = "User"
    ) -> Tuple[str, dict, list, str, int]:
        """
        Process a single conversation turn.

        Args:
            chat: Chat object from database
            user_input: User's message
            character: Character data (for character chats)
            world: World data (for world chats)
            user_name: User's display name

        Returns:
            Tuple of (clean_response_text, updated_state, updated_history, summary, msgs_since_summary)
        """
        # Parse current state
        state = json.loads(chat.state) if isinstance(chat.state, str) else chat.state
        history = json.loads(chat.history) if isinstance(chat.history, str) else chat.history
        summary = chat.summary or ""
        msgs_since_summary = chat.msgs_since_summary

        # Check if summarization is needed
        if msgs_since_summary >= self.summary_threshold and len(history) > 10:
            summary = await self._summarize_history(history, summary, state, character, world)
            # Keep only the most recent messages
            history = history[-5:]  # Keep last 5 messages as context
            msgs_since_summary = 0

        # Add user input to history
        history.append({"role": "user", "content": user_input})

        # Build system prompt with state and summary
        if character:
            system_prompt = build_character_prompt(
                character=character,
                state=state,
                summary=summary,
                user_name=user_name
            )
        elif world:
            system_prompt = build_world_prompt(world, user_name)
        else:
            raise ValueError("Either character or world must be provided")

        # Generate response
        response = await self.llm.generate(
            system_prompt=system_prompt,
            messages=history[-10:],  # Use last 10 messages for context
        )

        # Parse metadata from response
        clean_text, state_updates = self._parse_meta(response)

        # Update state based on parsed metadata
        if state_updates:
            if "affinity_change" in state_updates:
                state["affinity"] = max(0, min(100, state.get("affinity", 0) + state_updates["affinity_change"]))
            if "arousal_change" in state_updates:
                state["arousal"] = max(0, min(100, state.get("arousal", 0) + state_updates["arousal_change"]))
            if "mood" in state_updates:
                state["mood"] = state_updates["mood"]

        # Add assistant response to history
        history.append({"role": "assistant", "content": clean_text})

        # Increment counters
        msgs_since_summary += 1

        return clean_text, state, history, summary, msgs_since_summary

    async def _summarize_history(
        self,
        history: list,
        existing_summary: str,
        state: dict,
        character: Optional[dict] = None,
        world: Optional[dict] = None
    ) -> str:
        """
        Compress conversation history into a summary.

        Args:
            history: Full conversation history
            existing_summary: Previous summary (if any)
            state: Current emotional state
            character: Character data (if applicable)
            world: World data (if applicable)

        Returns:
            Updated summary text
        """
        # Take the oldest half of messages for summarization
        messages_to_summarize = history[:len(history) // 2]

        # Build context for summarization
        context_name = character["name"] if character else world["name"]

        summary_prompt = f"""You are summarizing a conversation between a user and {context_name}.

### EXISTING SUMMARY ###
{existing_summary if existing_summary else "This is the start of the conversation."}

### CURRENT EMOTIONAL STATE ###
Affinity: {state.get('affinity', 0)}/100
Arousal: {state.get('arousal', 0)}/100
Mood: {state.get('mood', 'neutral')}

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

        return summary.strip()

    def _format_messages_for_summary(self, messages: list) -> str:
        """Format messages for summarization prompt."""
        formatted = []
        for msg in messages:
            role = "Пользователь" if msg["role"] == "user" else "Персонаж"
            formatted.append(f"{role}: {msg['content']}")
        return "\n".join(formatted)

    def _parse_meta(self, response_text: str) -> Tuple[str, dict]:
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
            # Parse JSON from meta tags
            for match in matches:
                try:
                    updates = json.loads(match.strip())
                    state_updates.update(updates)
                except json.JSONDecodeError:
                    # Ignore malformed JSON
                    pass

        # Remove meta tags from response
        clean_text = re.sub(meta_pattern, '', response_text, flags=re.DOTALL).strip()

        return clean_text, state_updates
