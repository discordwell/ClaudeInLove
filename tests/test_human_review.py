"""Tests for the human-review queue and its DB-backed pause state."""

from src.core.models import MessageDirection, Platform, ScammerStatus
from src.safety.human_review import HumanReviewQueue


async def test_pause_and_resume_persist_to_db(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    queue = HumanReviewQueue(db)

    assert await queue.is_paused(scammer.id) is False

    await queue.pause(scammer.id)
    assert await queue.is_paused(scammer.id) is True
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.PAUSED

    await queue.resume(scammer.id)
    assert await queue.is_paused(scammer.id) is False
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.ACTIVE


async def test_pause_is_visible_to_a_separate_queue_instance(db):
    # Simulates the review_flagged.py tool (a different HumanReviewQueue) and
    # the running main loop sharing pause state through the database.
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)

    review_tool = HumanReviewQueue(db)
    main_loop_queue = HumanReviewQueue(db)

    await review_tool.pause(scammer.id)
    assert await main_loop_queue.is_paused(scammer.id) is True


async def test_flag_for_review_auto_pauses_and_logs(db, monkeypatch):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.OUTBOUND, "hi there")

    queue = HumanReviewQueue(db)
    monkeypatch.setattr(queue.config, "auto_pause_on_flag", True)

    await queue.flag_for_review(
        scammer_id=scammer.id,
        message=msg,
        proposed_response="i would be happy to help you",
        suspicion_score=0.85,
        reason="robotic phrasing",
    )

    assert await queue.is_paused(scammer.id) is True
    flags = await db.get_unreviewed_flags()
    assert len(flags) == 1
    assert flags[0].reason == "robotic phrasing"
    # the withheld reply is persisted so a reviewer can see it later
    assert flags[0].proposed_response == "i would be happy to help you"


async def test_flag_for_review_without_autopause_keeps_active(db, monkeypatch):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.OUTBOUND, "hi")

    queue = HumanReviewQueue(db)
    monkeypatch.setattr(queue.config, "auto_pause_on_flag", False)

    await queue.flag_for_review(
        scammer_id=scammer.id,
        message=msg,
        proposed_response="hello",
        suspicion_score=0.85,
        reason="testing",
    )

    assert await queue.is_paused(scammer.id) is False
    # the suspicion is still recorded for later review
    assert len(await db.get_unreviewed_flags()) == 1


async def test_get_pending_reviews_reflects_pause_state(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "are you real?")
    await db.log_suspicion(
        scammer.id, msg.id, 0.9, "AI probe", proposed_response="of course i'm real!",
    )

    queue = HumanReviewQueue(db)
    await queue.pause(scammer.id)

    reviews = await queue.get_pending_reviews()
    assert len(reviews) == 1
    assert reviews[0]["scammer_id"] == scammer.id
    assert reviews[0]["is_paused"] is True
    assert reviews[0]["proposed_response"] == "of course i'm real!"
