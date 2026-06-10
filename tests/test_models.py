"""Tests for data model serialization and helpers."""

from datetime import datetime

from src.core.models import (
    Scammer, Message, Persona, IncomingMessage,
    ScammerStatus, MessageDirection, Platform,
)


def test_scammer_dict_round_trip():
    original = Scammer(
        platform=Platform.MESSENGER,
        platform_id="+15551234567",
        display_name="Romeo",
        message_count=7,
        suspicion_flags=2,
        status=ScammerStatus.FLAGGED,
        notes="claims to be an oil rig engineer",
    )

    restored = Scammer.from_dict(original.to_dict())

    assert restored.id == original.id
    assert restored.platform == Platform.MESSENGER
    assert restored.platform_id == "+15551234567"
    assert restored.display_name == "Romeo"
    assert restored.message_count == 7
    assert restored.suspicion_flags == 2
    assert restored.status == ScammerStatus.FLAGGED
    assert restored.notes == "claims to be an oil rig engineer"


def test_scammer_from_dict_uses_defaults_for_missing_optionals():
    data = {
        "id": "abc",
        "platform": "signal",
        "platform_id": "+1",
        "first_contact": datetime.now().isoformat(),
        "last_contact": datetime.now().isoformat(),
    }
    scammer = Scammer.from_dict(data)
    assert scammer.message_count == 0
    assert scammer.suspicion_flags == 0
    assert scammer.status == ScammerStatus.ACTIVE
    assert scammer.display_name is None


def test_message_dict_round_trip():
    original = Message(
        id=42,
        scammer_id="s1",
        direction=MessageDirection.OUTBOUND,
        content="i miss you too 🥺",
        was_flagged=True,
        flag_reason="too long",
    )

    restored = Message.from_dict(original.to_dict())

    assert restored.id == 42
    assert restored.direction == MessageDirection.OUTBOUND
    assert restored.content == "i miss you too 🥺"
    assert restored.was_flagged is True
    assert restored.flag_reason == "too long"


def test_message_format_for_context_labels_speaker():
    inbound = Message(direction=MessageDirection.INBOUND, content="hello dear")
    outbound = Message(direction=MessageDirection.OUTBOUND, content="hi!")

    assert inbound.format_for_context() == "Them: hello dear"
    assert outbound.format_for_context() == "You: hi!"


def test_persona_to_dict_serializes_scraped_data_as_json():
    persona = Persona(name="Jordan", scraped_data={"location": "Chicago"})
    d = persona.to_dict()
    assert d["name"] == "Jordan"
    assert isinstance(d["scraped_data"], str)
    assert "Chicago" in d["scraped_data"]
    assert d["updated_at"] is None


def test_incoming_message_defaults_timestamp():
    msg = IncomingMessage(
        platform=Platform.SIGNAL,
        sender_id="+1",
        sender_name="Eve",
        content="hi",
    )
    assert isinstance(msg.timestamp, datetime)
    assert msg.platform_message_id is None
