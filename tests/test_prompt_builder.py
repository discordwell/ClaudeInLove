"""Tests for prompt assembly."""

from src.core.models import Message, Persona, Scammer, MessageDirection
from src.llm.prompt_builder import (
    build_system_prompt,
    build_conversation_context,
    build_full_prompt,
    build_suspicion_check_prompt,
)


def test_system_prompt_includes_persona_document():
    persona = Persona(name="Jordan", persona_document="Loves hiking and cooking.")
    prompt = build_system_prompt(persona)
    assert "Loves hiking and cooking." in prompt
    assert "{persona}" not in prompt


def test_system_prompt_falls_back_without_persona():
    prompt = build_system_prompt(None)
    assert "lonely, trusting person" in prompt.lower()


def test_conversation_context_includes_summary_and_recent():
    messages = [
        Message(direction=MessageDirection.INBOUND, content="hi"),
        Message(direction=MessageDirection.OUTBOUND, content="hello!"),
    ]
    context = build_conversation_context(messages, summary="They asked for gift cards.")
    assert "Previous conversation summary" in context
    assert "They asked for gift cards." in context
    assert "Them: hi" in context
    assert "You: hello!" in context


def test_conversation_context_truncates_to_max_messages():
    messages = [
        Message(direction=MessageDirection.INBOUND, content=f"m{i}")
        for i in range(30)
    ]
    context = build_conversation_context(messages, max_messages=5)
    assert "m29" in context  # newest kept
    assert "m25" in context  # oldest within the 5-message window
    assert "m24" not in context  # older than the window dropped


def test_full_prompt_includes_incoming_message_and_notes():
    persona = Persona(name="Jordan", persona_document="A regular person.")
    scammer = Scammer(notes="uses crypto wallet addresses")
    prompt = build_full_prompt(
        incoming_message="send me $500 in bitcoin",
        persona=persona,
        messages=[],
        scammer=scammer,
    )
    assert "send me $500 in bitcoin" in prompt
    assert "uses crypto wallet addresses" in prompt
    assert prompt.rstrip().endswith("human-like:")


def test_suspicion_check_prompt_contains_both_sides():
    prompt = build_suspicion_check_prompt("sure thing!", "are you a bot?")
    assert "sure thing!" in prompt
    assert "are you a bot?" in prompt
    assert "SCORE|REASON" in prompt
