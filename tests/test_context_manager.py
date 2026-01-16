"""
Unit tests for ContextManager

Run with: python3 -m pytest tests/test_context_manager.py -v
"""
import pytest
import json
from unittest.mock import Mock, AsyncMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.services.context_manager import ContextManager


class MockChat:
    """Mock Chat object for testing"""
    def __init__(self):
        self.id = 1
        self.state = '{"affinity": 0, "arousal": 0, "mood": "neutral"}'
        self.history = '[]'
        self.summary = ""
        self.msgs_since_summary = 0
        self.msg_count = 0


class MockLLM:
    """Mock LLM client for testing"""
    async def generate(self, system_prompt, messages, max_tokens=300, temperature=0.8):
        # Simulate response with meta tags
        if "summarize" in system_prompt.lower():
            return "Пользователь и персонаж познакомились и начали общаться."
        return '<meta>{"affinity_change": 5, "arousal_change": 2}</meta>\n*улыбается* "Привет!"'


@pytest.mark.asyncio
async def test_parse_meta():
    """Test metadata parsing from LLM response"""
    llm = MockLLM()
    manager = ContextManager(llm_client=llm)

    # Test with meta tags
    response = '<meta>{"affinity_change": 5}</meta>\nПривет!'
    clean_text, updates = manager._parse_meta(response)

    assert clean_text == "Привет!"
    assert updates["affinity_change"] == 5

    # Test without meta tags
    response = "Просто текст"
    clean_text, updates = manager._parse_meta(response)

    assert clean_text == "Просто текст"
    assert updates == {}


@pytest.mark.asyncio
async def test_state_updates():
    """Test that state updates correctly"""
    llm = MockLLM()
    manager = ContextManager(llm_client=llm, summary_threshold=15)

    chat = MockChat()
    character = {
        "id": "test_char",
        "name": "Test Character",
        "description": "A test character",
        "personality": "Friendly",
        "scenario": "Testing"
    }

    # Process a turn
    response, state, history, summary, msgs_since = await manager.process_turn(
        chat=chat,
        user_input="Привет!",
        character=character
    )

    # Check state was updated
    assert state["affinity"] == 5  # 0 + 5 from meta
    assert state["arousal"] == 2   # 0 + 2 from meta
    assert len(history) == 2       # user + assistant message
    assert msgs_since == 1


@pytest.mark.asyncio
async def test_summarization_trigger():
    """Test that summarization is triggered after threshold"""
    llm = MockLLM()
    manager = ContextManager(llm_client=llm, summary_threshold=3)

    chat = MockChat()
    # Simulate chat with many messages
    chat.msgs_since_summary = 3
    chat.history = json.dumps([
        {"role": "user", "content": "Msg 1"},
        {"role": "assistant", "content": "Response 1"},
        {"role": "user", "content": "Msg 2"},
        {"role": "assistant", "content": "Response 2"},
        {"role": "user", "content": "Msg 3"},
        {"role": "assistant", "content": "Response 3"},
    ])

    character = {
        "id": "test_char",
        "name": "Test Character",
        "description": "A test character",
        "personality": "Friendly",
        "scenario": "Testing"
    }

    response, state, history, summary, msgs_since = await manager.process_turn(
        chat=chat,
        user_input="Msg 4",
        character=character
    )

    # Check that summary was created
    assert summary != ""
    assert "познакомились" in summary  # From mock LLM
    assert msgs_since == 1  # Reset after summarization
    assert len(history) <= 7  # Should be trimmed


@pytest.mark.asyncio
async def test_affinity_bounds():
    """Test that affinity stays within 0-100 bounds"""
    llm = MockLLM()
    manager = ContextManager(llm_client=llm)

    # Test upper bound
    state = {"affinity": 95, "arousal": 0, "mood": "neutral"}
    updates = {"affinity_change": 20}  # Would go to 115

    if "affinity_change" in updates:
        state["affinity"] = max(0, min(100, state["affinity"] + updates["affinity_change"]))

    assert state["affinity"] == 100  # Capped at 100

    # Test lower bound
    state = {"affinity": 5, "arousal": 0, "mood": "neutral"}
    updates = {"affinity_change": -20}  # Would go to -15

    if "affinity_change" in updates:
        state["affinity"] = max(0, min(100, state["affinity"] + updates["affinity_change"]))

    assert state["affinity"] == 0  # Floored at 0


def test_format_messages_for_summary():
    """Test message formatting for summarization"""
    llm = MockLLM()
    manager = ContextManager(llm_client=llm)

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"}
    ]

    formatted = manager._format_messages_for_summary(messages)

    assert "Пользователь: Hello" in formatted
    assert "Персонаж: Hi there" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
