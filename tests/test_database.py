"""Tests for the SQLite persistence layer."""

import aiosqlite

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
    # proposed_response is optional and defaults to NULL/None
    assert flags[0].proposed_response is None

    # logging a suspicion bumps the scammer's flag counter
    refreshed = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    assert refreshed.suspicion_flags == 1


async def test_log_suspicion_persists_proposed_response(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "are you real?")

    await db.log_suspicion(
        scammer.id, msg.id, 0.85, "robotic phrasing",
        proposed_response="I would be happy to help you with that.",
    )

    flags = await db.get_unreviewed_flags()
    assert flags[0].proposed_response == "I would be happy to help you with that."


async def test_mark_flag_reviewed_drains_it_from_the_queue(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "are you real?")
    flag = await db.log_suspicion(scammer.id, msg.id, 0.9, "AI probe", proposed_response="yes!")

    # Initially the flag is pending review.
    pending = await db.get_unreviewed_flags()
    assert [f.id for f in pending] == [flag.id]
    assert pending[0].human_reviewed is False
    assert pending[0].reviewed_at is None

    await db.mark_flag_reviewed(flag.id)

    # It no longer shows up as needing review.
    assert await db.get_unreviewed_flags() == []


async def test_mark_flag_reviewed_only_affects_the_named_flag(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "hi")
    flag_a = await db.log_suspicion(scammer.id, msg.id, 0.9, "first")
    flag_b = await db.log_suspicion(scammer.id, msg.id, 0.8, "second")

    await db.mark_flag_reviewed(flag_a.id)

    remaining = await db.get_unreviewed_flags()
    assert [f.id for f in remaining] == [flag_b.id]


async def test_connect_migrates_legacy_suspicion_log(tmp_path):
    """A DB predating both back-filled suspicion_log columns upgrades cleanly."""
    path = tmp_path / "legacy.db"

    # Build the oldest suspicion_log shape: missing BOTH proposed_response and
    # reviewed_at. (reviewed_at has always been in the CREATE TABLE, but
    # get_unreviewed_flags now reads it, so the migration must guarantee it on
    # any older DB — this exercises that step.)
    legacy = await aiosqlite.connect(path)
    await legacy.execute(
        """CREATE TABLE suspicion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scammer_id TEXT NOT NULL,
            message_id INTEGER,
            suspicion_score REAL,
            reason TEXT,
            human_reviewed BOOLEAN DEFAULT FALSE
        )"""
    )
    await legacy.commit()
    await legacy.close()

    db = Database(db_path=path)
    await db.connect()  # runs the migration; must not raise
    try:
        # Re-running the migration is a no-op now that the columns exist.
        await db._migrate()

        scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
        msg = await db.add_message(scammer.id, MessageDirection.OUTBOUND, "hi")
        flag = await db.log_suspicion(
            scammer.id, msg.id, 0.9, "robotic", proposed_response="hello there",
        )

        # Both back-filled columns are usable: reading reviewed_at (added by the
        # migration) does not raise, and proposed_response round-trips.
        flags = await db.get_unreviewed_flags()
        assert flags[0].proposed_response == "hello there"
        assert flags[0].reviewed_at is None

        # The freshly-added reviewed_at column is writable, so the flag drains.
        await db.mark_flag_reviewed(flag.id)
        assert await db.get_unreviewed_flags() == []
    finally:
        await db.close()
