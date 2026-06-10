"""Tests for the SQLite persistence layer."""

from src.core.database import Database
from src.core.models import (
    Persona, ScammerStatus, MessageDirection, Platform,
)


async def test_get_or_create_scammer_is_idempotent(db):
    a = await db.get_or_create_scammer(Platform.SIGNAL, "+15550001111", "Romeo")
    b = await db.get_or_create_scammer(Platform.SIGNAL, "+15550001111", "Romeo")
    assert a.id == b.id

    actives = await db.get_active_scammers()
    assert len(actives) == 1


async def test_add_message_updates_count_and_orders_chronologically(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)

    await db.add_message(scammer.id, MessageDirection.INBOUND, "first")
    await db.add_message(scammer.id, MessageDirection.OUTBOUND, "second")
    await db.add_message(scammer.id, MessageDirection.INBOUND, "third")

    assert await db.get_message_count(scammer.id) == 3

    messages = await db.get_messages(scammer.id)
    assert [m.content for m in messages] == ["first", "second", "third"]

    # message_count on the scammer row is incremented per message
    refreshed = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    assert refreshed.message_count == 3


async def test_recent_messages_respects_count(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    for i in range(10):
        await db.add_message(scammer.id, MessageDirection.INBOUND, f"m{i}")

    recent = await db.get_recent_messages(scammer.id, count=3)
    assert [m.content for m in recent] == ["m7", "m8", "m9"]


async def test_status_methods(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.ACTIVE

    await db.set_scammer_status(scammer.id, ScammerStatus.PAUSED)
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.PAUSED
    assert await db.get_paused_scammer_ids() == [scammer.id]

    await db.set_scammer_status(scammer.id, ScammerStatus.ACTIVE)
    assert await db.get_paused_scammer_ids() == []


async def test_get_scammer_status_unknown_returns_none(db):
    assert await db.get_scammer_status("does-not-exist") is None


async def test_status_persists_across_reconnect(tmp_path):
    path = tmp_path / "persist.db"

    db1 = Database(db_path=path)
    await db1.connect()
    scammer = await db1.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    await db1.set_scammer_status(scammer.id, ScammerStatus.PAUSED)
    await db1.close()

    db2 = Database(db_path=path)
    await db2.connect()
    try:
        assert await db2.get_scammer_status(scammer.id) == ScammerStatus.PAUSED
    finally:
        await db2.close()


async def test_context_snapshot_round_trip(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)

    assert await db.get_latest_snapshot(scammer.id) is None

    await db.save_context_snapshot(scammer.id, "summary", "first summary", 0, 10)
    await db.save_context_snapshot(scammer.id, "summary", "newer summary", 0, 30)

    latest = await db.get_latest_snapshot(scammer.id)
    assert latest.content == "newer summary"
    assert latest.message_range_end == 30


async def test_persona_save_and_get(db):
    persona = Persona(
        name="Jordan Taylor",
        scraped_data={"location": "Chicago"},
        persona_document="A regular person.",
    )
    saved = await db.save_persona(persona)
    assert saved.id

    loaded = await db.get_persona()
    assert loaded.name == "Jordan Taylor"
    assert loaded.scraped_data == {"location": "Chicago"}
    assert loaded.persona_document == "A regular person."


async def test_suspicion_log_and_unreviewed_flags(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.OUTBOUND, "hi")

    await db.log_suspicion(scammer.id, msg.id, 0.9, "too perfect")

    flags = await db.get_unreviewed_flags()
    assert len(flags) == 1
    assert flags[0].suspicion_score == 0.9
    assert flags[0].reason == "too perfect"

    # logging a suspicion bumps the scammer's flag counter
    refreshed = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    assert refreshed.suspicion_flags == 1
