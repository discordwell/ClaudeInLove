"""Tests for the operator stats overview and its formatting helpers."""

from datetime import datetime, timedelta

from src.core.models import MessageDirection, Platform, ScammerStatus
from src.core.stats import (
    ConversationStat,
    gather_overview,
    human_duration,
)


def _stat(first, last):
    return ConversationStat(
        scammer_id="s",
        display_name=None,
        platform="signal",
        status="active",
        message_count=0,
        suspicion_flags=0,
        first_contact=first,
        last_contact=last,
    )


def test_engagement_is_first_to_last_contact():
    start = datetime(2026, 1, 1, 12, 0, 0)
    stat = _stat(start, start + timedelta(hours=3))
    assert stat.engagement == timedelta(hours=3)


def test_engagement_clamps_negative_to_zero():
    start = datetime(2026, 1, 1, 12, 0, 0)
    # last before first (clock skew) must not produce a negative duration.
    stat = _stat(start, start - timedelta(hours=1))
    assert stat.engagement == timedelta()


def test_human_duration_formats():
    assert human_duration(timedelta(seconds=5)) == "<1m"
    assert human_duration(timedelta(minutes=2)) == "2m"
    assert human_duration(timedelta(hours=5, minutes=2)) == "5h 2m"
    assert human_duration(timedelta(hours=5)) == "5h"
    assert human_duration(timedelta(days=3, hours=4)) == "3d 4h"
    assert human_duration(timedelta(days=3)) == "3d"


async def test_overview_of_empty_db_is_all_zero(db):
    overview = await gather_overview(db)
    assert overview.total_scammers == 0
    assert overview.total_messages == 0
    assert overview.inbound_messages == 0
    assert overview.outbound_messages == 0
    assert overview.pending_reviews == 0
    assert overview.total_engagement == timedelta()
    assert overview.conversations == []
    # Every status key is present and zero.
    assert overview.by_status == {s.value: 0 for s in ScammerStatus}


async def test_overview_aggregates_across_scammers(db):
    a = await db.get_or_create_scammer(Platform.SIGNAL, "+1", "Al")
    b = await db.get_or_create_scammer(Platform.MESSENGER, "+2", "Bea")
    await db.set_scammer_status(b.id, ScammerStatus.PAUSED)

    await db.add_message(a.id, MessageDirection.INBOUND, "hi")
    await db.add_message(a.id, MessageDirection.OUTBOUND, "hey there")
    await db.add_message(b.id, MessageDirection.INBOUND, "send money")

    msg = await db.get_recent_messages(b.id, 1)
    await db.log_suspicion(b.id, msg[0].id, 0.95, "robotic", proposed_response="ok")

    overview = await gather_overview(db)

    assert overview.total_scammers == 2
    assert overview.by_status["active"] == 1
    assert overview.by_status["paused"] == 1
    assert overview.inbound_messages == 2
    assert overview.outbound_messages == 1
    assert overview.total_messages == 3
    assert overview.pending_reviews == 1

    # Per-conversation rows carry the stored counters.
    by_id = {c.scammer_id: c for c in overview.conversations}
    assert by_id[a.id].message_count == 2
    assert by_id[a.id].suspicion_flags == 0
    assert by_id[b.id].message_count == 1
    assert by_id[b.id].suspicion_flags == 1
    assert by_id[b.id].status == "paused"


async def test_overview_total_engagement_sums_conversation_spans(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    # Backdate first_contact so the engagement span is a known, non-trivial value.
    earlier = (datetime.now() - timedelta(hours=2)).isoformat()
    await db._conn.execute(
        "UPDATE scammers SET first_contact = ? WHERE id = ?", (earlier, scammer.id)
    )
    await db._conn.commit()

    overview = await gather_overview(db)
    # Roughly two hours (allow a small window for test execution time).
    assert timedelta(hours=1, minutes=59) <= overview.total_engagement <= timedelta(hours=2, minutes=1)
