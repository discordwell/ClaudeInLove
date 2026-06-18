"""
Orchestration tests for ClaudeInLove.handle_incoming_message.

These exercise the real database, context manager, suspicion checker and
human-review queue together, faking only the two browser-driven clients
(Signal and ChatGPT). The human-like send delay is forced to zero so the
loop runs instantly.
"""

from src.core.main_loop import ClaudeInLove
from src.core.models import (
    IncomingMessage, Platform, MessageDirection, ScammerStatus,
)
from src.llm.context_manager import ContextManager
from src.safety.suspicion_checker import SuspicionChecker
from src.safety.human_review import HumanReviewQueue
from src.persona.persona_builder import create_default_persona


# A drafted reply riddled with robotic tells; scores well above threshold.
ROBOTIC_REPLY = (
    "I apologize. I understand. As an AI, I'm here to help. "
    "Is there anything else? I'd be happy to. Let me know if you need anything."
)

SENDER = "+15550001111"


class FakeChatGPT:
    """Stand-in for the Playwright ChatGPT client."""

    def __init__(self, response: str = "haha yeah maybe... we'll see"):
        self.response = response
        self.prompts = []

    async def send_message(self, prompt: str, timeout: int = 120) -> str:
        self.prompts.append(prompt)
        return self.response


class FakeSignal:
    """Stand-in for the Signal Desktop client."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.sent = []

    async def send_message(self, recipient_id: str, content: str) -> bool:
        self.sent.append((recipient_id, content))
        return self.ok


def make_app(db, monkeypatch, chatgpt=None, signal=None):
    """Wire up a ClaudeInLove with real logic and fake browser clients."""
    app = ClaudeInLove()
    app.db = db
    app.chatgpt = chatgpt or FakeChatGPT()
    app.signal = signal or FakeSignal()
    app.context_manager = ContextManager(db, app.chatgpt)
    app.suspicion_checker = SuspicionChecker(app.chatgpt)
    app.review_queue = HumanReviewQueue(db)
    app.persona = create_default_persona()
    # Make the human-like response delay instant and deterministic.
    monkeypatch.setattr(app.config, "min_response_delay", 0)
    monkeypatch.setattr(app.config, "max_response_delay", 0)
    return app


def incoming(
    content: str,
    sender: str = SENDER,
    name: str = "Romeo",
    platform_message_id: str = None,
    synthetic_id: bool = False,
):
    return IncomingMessage(
        platform=Platform.SIGNAL,
        sender_id=sender,
        sender_name=name,
        content=content,
        platform_message_id=platform_message_id,
        synthetic_id=synthetic_id,
    )


async def test_happy_path_sends_and_persists_both_messages(db, monkeypatch):
    chatgpt = FakeChatGPT("haha yeah maybe... we'll see")
    signal = FakeSignal(ok=True)
    app = make_app(db, monkeypatch, chatgpt=chatgpt, signal=signal)

    await app.handle_incoming_message(incoming("hey beautiful how are you"))

    scammer = await db.get_or_create_scammer(Platform.SIGNAL, SENDER)
    msgs = await db.get_messages(scammer.id)
    assert [m.direction for m in msgs] == [
        MessageDirection.INBOUND,
        MessageDirection.OUTBOUND,
    ]
    assert msgs[0].content == "hey beautiful how are you"
    assert msgs[1].content == "haha yeah maybe... we'll see"
    assert msgs[1].was_flagged is False

    # Reply actually went out over Signal.
    assert signal.sent == [(SENDER, "haha yeah maybe... we'll see")]

    # Clean exchange: not paused, nothing queued for review.
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.ACTIVE
    assert await db.get_unreviewed_flags() == []


async def test_paused_scammer_is_skipped_entirely(db, monkeypatch):
    signal = FakeSignal()
    app = make_app(db, monkeypatch, signal=signal)

    # Pre-create and pause this scammer (e.g. by a human reviewer).
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, SENDER, "Romeo")
    await app.review_queue.pause(scammer.id)

    await app.handle_incoming_message(incoming("you there??"))

    # Nothing stored, nothing sent.
    assert await db.get_message_count(scammer.id) == 0
    assert signal.sent == []
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.PAUSED


async def test_empty_response_is_not_sent(db, monkeypatch):
    chatgpt = FakeChatGPT("")  # ChatGPT produced nothing
    signal = FakeSignal()
    app = make_app(db, monkeypatch, chatgpt=chatgpt, signal=signal)

    await app.handle_incoming_message(incoming("hello?"))

    scammer = await db.get_or_create_scammer(Platform.SIGNAL, SENDER)
    msgs = await db.get_messages(scammer.id)
    # Inbound is recorded, but no outbound and no send attempt.
    assert [m.direction for m in msgs] == [MessageDirection.INBOUND]
    assert signal.sent == []


async def test_flagged_reply_autopauses_and_withholds(db, monkeypatch):
    chatgpt = FakeChatGPT(ROBOTIC_REPLY)
    signal = FakeSignal()
    app = make_app(db, monkeypatch, chatgpt=chatgpt, signal=signal)
    monkeypatch.setattr(app.config, "auto_pause_on_flag", True)

    await app.handle_incoming_message(incoming("why are you being weird"))

    scammer = await db.get_or_create_scammer(Platform.SIGNAL, SENDER)

    # Reply was withheld: nothing sent, no outbound stored.
    assert signal.sent == []
    msgs = await db.get_messages(scammer.id)
    assert [m.direction for m in msgs] == [MessageDirection.INBOUND]

    # Conversation paused for a human to look at.
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.PAUSED

    # The withheld reply is persisted so the reviewer can read it.
    flags = await db.get_unreviewed_flags()
    assert len(flags) == 1
    assert flags[0].proposed_response == ROBOTIC_REPLY
    assert flags[0].suspicion_score >= app.config.suspicion_threshold


async def test_flagged_reply_without_autopause_still_sends(db, monkeypatch):
    chatgpt = FakeChatGPT(ROBOTIC_REPLY)
    signal = FakeSignal(ok=True)
    app = make_app(db, monkeypatch, chatgpt=chatgpt, signal=signal)
    monkeypatch.setattr(app.config, "auto_pause_on_flag", False)

    await app.handle_incoming_message(incoming("hello dear"))

    scammer = await db.get_or_create_scammer(Platform.SIGNAL, SENDER)

    # Sent despite the flag (operator chose not to auto-pause).
    assert signal.sent == [(SENDER, ROBOTIC_REPLY)]
    msgs = await db.get_messages(scammer.id)
    assert [m.direction for m in msgs] == [
        MessageDirection.INBOUND,
        MessageDirection.OUTBOUND,
    ]
    assert msgs[1].was_flagged is True
    assert msgs[1].flag_reason

    # Still active, but the suspicion (with the reply) is recorded for review.
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.ACTIVE
    flags = await db.get_unreviewed_flags()
    assert len(flags) == 1
    assert flags[0].proposed_response == ROBOTIC_REPLY


async def test_ai_probe_forces_review_even_when_reply_scores_low(db, monkeypatch):
    # The drafted reply is natural; the scammer is openly probing for a bot.
    # The probe phrase keeps the suspicion score below the threshold here, so
    # what escalates this to review is the probe itself, not the score. The
    # appended "AI probe" reason (only added when is_ai_probe and the score is
    # sub-threshold) pins that it took the probe branch.
    chatgpt = FakeChatGPT("i'm right here babe lol")
    signal = FakeSignal()
    app = make_app(db, monkeypatch, chatgpt=chatgpt, signal=signal)
    monkeypatch.setattr(app.config, "auto_pause_on_flag", True)

    await app.handle_incoming_message(incoming("wait... are you a bot??"))

    scammer = await db.get_or_create_scammer(Platform.SIGNAL, SENDER)

    # The probe forces a withheld review despite the sub-threshold reply.
    assert signal.sent == []
    assert await db.get_scammer_status(scammer.id) == ScammerStatus.PAUSED

    flags = await db.get_unreviewed_flags()
    assert len(flags) == 1
    assert flags[0].suspicion_score < app.config.suspicion_threshold
    assert flags[0].proposed_response == "i'm right here babe lol"
    assert "AI probe" in flags[0].reason


async def test_duplicate_stable_id_is_answered_only_once(db, monkeypatch):
    # The same Signal message (same real platform id) is delivered twice — e.g.
    # the in-memory seen-set was lost to a restart and the unread conversation
    # got re-extracted. The second delivery must be skipped entirely.
    chatgpt = FakeChatGPT("hey you! how's your day")
    signal = FakeSignal(ok=True)
    app = make_app(db, monkeypatch, chatgpt=chatgpt, signal=signal)

    msg = incoming("morning love", platform_message_id="sig-abc")
    await app.handle_incoming_message(msg)
    await app.handle_incoming_message(msg)  # same id again

    scammer = await db.get_or_create_scammer(Platform.SIGNAL, SENDER)
    msgs = await db.get_messages(scammer.id)
    # Exactly one inbound + one outbound; the duplicate did not double-text.
    assert [m.direction for m in msgs] == [
        MessageDirection.INBOUND,
        MessageDirection.OUTBOUND,
    ]
    assert signal.sent == [(SENDER, "hey you! how's your day")]


async def test_synthetic_id_duplicate_is_not_suppressed_across_calls(db, monkeypatch):
    # A content fingerprint (synthetic_id=True) collides for identical text, so
    # durable dedup must NOT permanently suppress it — a scammer who repeats the
    # same line should still get a reply. (Within a live session the platform
    # client's own seen-set handles genuine repeats; the DB layer stays out of
    # it here.)
    chatgpt = FakeChatGPT("aww you're sweet")
    signal = FakeSignal(ok=True)
    app = make_app(db, monkeypatch, chatgpt=chatgpt, signal=signal)

    fp = "fp:deadbeef"
    await app.handle_incoming_message(
        incoming("good morning beautiful", platform_message_id=fp, synthetic_id=True)
    )
    await app.handle_incoming_message(
        incoming("good morning beautiful", platform_message_id=fp, synthetic_id=True)
    )

    scammer = await db.get_or_create_scammer(Platform.SIGNAL, SENDER)
    # Both deliveries were processed (not gated by the durable check).
    assert signal.sent == [
        (SENDER, "aww you're sweet"),
        (SENDER, "aww you're sweet"),
    ]
    inbound = [
        m for m in await db.get_messages(scammer.id)
        if m.direction == MessageDirection.INBOUND
    ]
    assert len(inbound) == 2


async def test_send_failure_does_not_store_outbound(db, monkeypatch):
    chatgpt = FakeChatGPT("sure, sounds good")
    signal = FakeSignal(ok=False)  # Signal send fails
    app = make_app(db, monkeypatch, chatgpt=chatgpt, signal=signal)

    await app.handle_incoming_message(incoming("good morning sweetheart"))

    scammer = await db.get_or_create_scammer(Platform.SIGNAL, SENDER)
    msgs = await db.get_messages(scammer.id)
    # A send was attempted, but only the inbound is persisted.
    assert signal.sent == [(SENDER, "sure, sounds good")]
    assert [m.direction for m in msgs] == [MessageDirection.INBOUND]
