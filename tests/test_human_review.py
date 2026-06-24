"""Tests for the human-review queue and its DB-backed pause state."""

from src.core.models import MessageDirection, Platform, Persona, ScammerStatus
from src.llm.prompt_builder import build_full_prompt
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
    assert reviews[0]["status"] == "paused"
    assert reviews[0]["proposed_response"] == "of course i'm real!"


async def test_archive_persists_to_db(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    queue = HumanReviewQueue(db)

    await queue.archive(scammer.id)

    assert await db.get_scammer_status(scammer.id) == ScammerStatus.ARCHIVED
    # Archiving is a hold like pausing, but a distinct lifecycle state.
    assert await queue.is_paused(scammer.id) is False


async def test_add_note_appends_and_ignores_blanks(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    queue = HumanReviewQueue(db)

    first = await queue.add_note(scammer.id, "claims to be an oil-rig engineer")
    assert first == "claims to be an oil-rig engineer"

    # A second note accumulates (newline-separated) rather than overwriting.
    second = await queue.add_note(scammer.id, "asked for $500 in gift cards")
    assert second == "claims to be an oil-rig engineer\nasked for $500 in gift cards"
    assert await db.get_scammer_notes(scammer.id) == second

    # Blank/whitespace notes are no-ops (no stray blank line), returning current.
    assert await queue.add_note(scammer.id, "   ") == second
    assert await db.get_scammer_notes(scammer.id) == second


async def test_add_note_does_not_change_status_or_flags(db):
    # Taking a note is not a review decision: status and the flag queue are
    # untouched (unlike resume/pause/archive).
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "hi")
    await db.log_suspicion(scammer.id, msg.id, 0.9, "robotic", proposed_response="hello")

    queue = HumanReviewQueue(db)
    await queue.add_note(scammer.id, "noted")

    assert await db.get_scammer_status(scammer.id) == ScammerStatus.ACTIVE
    assert len(await db.get_unreviewed_flags()) == 1


async def test_get_pending_reviews_includes_notes(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "are you real?")
    await db.log_suspicion(scammer.id, msg.id, 0.9, "AI probe", proposed_response="yes!")

    queue = HumanReviewQueue(db)
    await queue.add_note(scammer.id, "uses a fake army profile photo")

    reviews = await queue.get_pending_reviews()
    assert reviews[0]["notes"] == "uses a fake army profile photo"


async def test_accumulated_notes_flow_into_the_reply_prompt(db):
    # The whole point of notes: they steer future replies. Prove the end-to-end
    # loop (review tool -> DB -> reload -> prompt) carries BOTH accumulated lines
    # of a multi-session note into build_full_prompt, so the persona stays
    # consistent with what the operator has learned.
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    queue = HumanReviewQueue(db)
    await queue.add_note(scammer.id, "claims to be an oil-rig engineer")
    await queue.add_note(scammer.id, "asked for $500 in gift cards")

    # Reload so the notes come from the database, not the in-memory object.
    reloaded = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    prompt = build_full_prompt(
        incoming_message="did you send the cards?",
        persona=Persona(name="Jordan", persona_document="A regular person."),
        messages=[],
        scammer=reloaded,
    )
    assert "claims to be an oil-rig engineer" in prompt
    assert "asked for $500 in gift cards" in prompt


async def test_get_pending_reviews_reports_archived_status(db):
    # A conversation can still carry an unreviewed flag after being archived;
    # the review row must report its real status, not just paused/active.
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "send me a steam card")
    await db.log_suspicion(scammer.id, msg.id, 0.95, "money request", proposed_response="hmm")

    queue = HumanReviewQueue(db)
    await queue.archive(scammer.id)

    reviews = await queue.get_pending_reviews()
    assert reviews[0]["status"] == "archived"
    assert reviews[0]["is_paused"] is False


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


async def test_interactive_archive_marks_flag_reviewed_and_archives(db, monkeypatch):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "are you a bot?")
    await db.log_suspicion(scammer.id, msg.id, 0.9, "AI probe", proposed_response="nope")

    monkeypatch.setattr("builtins.input", lambda *a, **k: "a")
    await interactive_review_session(db)

    # Archiving is a terminal decision: the conversation is retired AND the flag
    # drains from the queue, so a second run shows nothing.
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.ARCHIVED
    assert await db.get_unreviewed_flags() == []


def _scripted_input(responses):
    """Return a fake ``input`` that yields the given responses in order.

    If the code under test asks for more input than was scripted, fail with a
    clear ``AssertionError`` rather than letting the bare ``StopIteration`` turn
    into an opaque ``RuntimeError: coroutine raised StopIteration`` (PEP 479) —
    an under-supplied test should point at itself, not at the event loop.
    """
    it = iter(responses)

    def _fake_input(*args, **kwargs):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(
                "interactive session requested more input than was scripted"
            )

    return _fake_input


async def test_interactive_note_then_resume(db, monkeypatch):
    # Taking a note re-prompts (it is not a decision), then the operator resumes.
    # The note is saved and the flag is drained by the eventual Resume.
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "are you a bot?")
    await db.log_suspicion(scammer.id, msg.id, 0.9, "AI probe", proposed_response="no!")
    await HumanReviewQueue(db).pause(scammer.id)

    # 'n' -> note text -> 'r' (resume). The note prompt is a second input() call.
    monkeypatch.setattr(
        "builtins.input",
        _scripted_input(["n", "claims to be a widowed surgeon", "r"]),
    )
    await interactive_review_session(db)

    assert await db.get_scammer_notes(scammer.id) == "claims to be a widowed surgeon"
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.ACTIVE
    assert await db.get_unreviewed_flags() == []


async def test_interactive_blank_note_is_skipped_then_skip(db, monkeypatch):
    # Cancelling the note prompt (blank) adds nothing; a following Skip leaves the
    # flag pending for later — proving the note path never marks a flag reviewed.
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    msg = await db.add_message(scammer.id, MessageDirection.INBOUND, "hello?")
    await db.log_suspicion(scammer.id, msg.id, 0.9, "robotic", proposed_response="hi")

    monkeypatch.setattr("builtins.input", _scripted_input(["n", "   ", "s"]))
    await interactive_review_session(db)

    assert await db.get_scammer_notes(scammer.id) is None
    assert len(await db.get_unreviewed_flags()) == 1
