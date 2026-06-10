"""Tests for conversation context compression logic."""

from src.core.models import MessageDirection, Platform
from src.llm.context_manager import ContextManager, RECENT_WINDOW, SUMMARY_THRESHOLD


class FakeLLM:
    def __init__(self, response: str):
        self._response = response
        self.calls = []

    async def send_message(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


def test_estimate_token_count():
    cm = ContextManager(db=None)
    assert cm.estimate_token_count("a" * 40) == 10
    assert cm.estimate_token_count("") == 0


async def test_should_compress_below_threshold_is_false(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    await db.add_message(scammer.id, MessageDirection.INBOUND, "hi")

    cm = ContextManager(db)
    assert await cm.should_compress(scammer.id) is False


async def test_should_compress_above_threshold_without_snapshot(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    for i in range(SUMMARY_THRESHOLD + 5):
        await db.add_message(scammer.id, MessageDirection.INBOUND, f"m{i}")

    cm = ContextManager(db)
    assert await cm.should_compress(scammer.id) is True


async def test_should_compress_false_when_snapshot_is_fresh(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    total = SUMMARY_THRESHOLD + 5
    for i in range(total):
        await db.add_message(scammer.id, MessageDirection.INBOUND, f"m{i}")

    # Snapshot covering everything but the most recent window -> fresh.
    await db.save_context_snapshot(
        scammer.id, "summary", "s", 0, total - RECENT_WINDOW + 1
    )

    cm = ContextManager(db)
    assert await cm.should_compress(scammer.id) is False


async def test_generates_summary_when_history_is_long(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    for i in range(SUMMARY_THRESHOLD + 5):
        await db.add_message(scammer.id, MessageDirection.INBOUND, f"m{i}")

    llm = FakeLLM("They keep asking for money; we keep stalling.")
    cm = ContextManager(db, llm)

    messages, summary = await cm.get_context_for_scammer(scammer.id)

    assert summary == "They keep asking for money; we keep stalling."
    assert len(llm.calls) == 1
    assert len(messages) == RECENT_WINDOW

    # Summary should have been persisted as a snapshot.
    snapshot = await db.get_latest_snapshot(scammer.id)
    assert snapshot is not None
    assert snapshot.content == summary


async def test_get_compressed_context_trims_to_budget(db):
    scammer = await db.get_or_create_scammer(Platform.SIGNAL, "+1", None)
    for i in range(10):
        await db.add_message(scammer.id, MessageDirection.INBOUND, "x" * 40)

    cm = ContextManager(db)
    # Very tight budget forces trimming down to the floor of 5 messages.
    messages, summary = await cm.get_compressed_context(scammer.id, max_tokens=5)
    assert len(messages) == 5
    assert summary is None
