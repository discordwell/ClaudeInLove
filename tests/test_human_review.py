"""Tests for the human-review queue and its DB-backed pause state."""

from src.core.models import MessageDirection, Platform, ScammerStatus
from src.safety.human_review import HumanReviewQueue, interactive_review_session


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


async def test_get_pending_reviews_shows_the_flagged_message_not_the_latest(db):
    # The review must show the message the flag was raised against, even when a
    # newer message exists. With auto_pause disabled the bot's own reply is
    # stored *after* the flag, so "the latest message" is the wrong one — and
    # showing our outbound reply as "their message" would mislead the reviewer.
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    flagged = await db.add_message(scammer.id, MessageDirection.INBOUND, "are you real?")
    await db.log_suspicion(
        scammer.id, flagged.id, 0.9, "AI probe", proposed_response="of course!",
    )
    # A later outbound reply becomes the most recent message in the table.
    await db.add_message(scammer.id, MessageDirection.OUTBOUND, "of course i'm real!!")

    reviews = await HumanReviewQueue(db).get_pending_reviews()
    assert len(reviews) == 1
    assert reviews[0]["message"] == "are you real?"


async def test_get_pending_reviews_pairs_each_flag_with_its_own_message(db):
    # Two flags on the same scammer for two different messages: each review row
    # must carry the right message, not a single shared "most recent" one.
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    m1 = await db.add_message(scammer.id, MessageDirection.INBOUND, "send me a gift card")
    await db.log_suspicion(scammer.id, m1.id, 0.95, "money request", proposed_response="hmm")
    m2 = await db.add_message(scammer.id, MessageDirection.INBOUND, "are you a bot?")
    await db.log_suspicion(scammer.id, m2.id, 0.8, "AI probe", proposed_response="no!")

    reviews = await HumanReviewQueue(db).get_pending_reviews()
    by_message = {r["message"] for r in reviews}
    assert by_message == {"send me a gift card", "are you a bot?"}


async def test_mark_reviewed_removes_flag_from_pending(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "are you a bot?")
    flag = await db.log_suspicion(scammer.id, msg.id, 0.9, "AI probe", proposed_response="no!")

    queue = HumanReviewQueue(db)
    assert len(await queue.get_pending_reviews()) == 1

    await queue.mark_reviewed(flag.id)
    assert await queue.get_pending_reviews() == []


async def test_interactive_resume_marks_flag_reviewed(db, monkeypatch):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "are you a bot?")
    await db.log_suspicion(scammer.id, msg.id, 0.9, "AI probe", proposed_response="no way!")
    await HumanReviewQueue(db).pause(scammer.id)

    monkeypatch.setattr("builtins.input", lambda *a, **k: "r")
    await interactive_review_session(db)

    # The conversation is resumed AND the flag is drained from the queue, so a
    # second run of the review tool would show nothing.
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.ACTIVE
    assert await db.get_unreviewed_flags() == []


async def test_interactive_pause_marks_flag_reviewed(db, monkeypatch):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "send me money")
    await db.log_suspicion(scammer.id, msg.id, 0.95, "robotic", proposed_response="ok sure")

    monkeypatch.setattr("builtins.input", lambda *a, **k: "p")
    await interactive_review_session(db)

    # Keeping it paused is still a decision: the flag drains, but the scammer
    # stays paused.
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.PAUSED
    assert await db.get_unreviewed_flags() == []


async def test_interactive_skip_leaves_flag_pending(db, monkeypatch):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "hello?")
    await db.log_suspicion(scammer.id, msg.id, 0.9, "robotic", proposed_response="hi")

    monkeypatch.setattr("builtins.input", lambda *a, **k: "s")
    await interactive_review_session(db)

    # Skip is "decide later": the flag remains for the next session.
    assert len(await db.get_unreviewed_flags()) == 1
