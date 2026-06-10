"""Tests for the AI-suspicion heuristics and LLM result parsing."""

from src.safety.suspicion_checker import SuspicionChecker


class FakeLLM:
    """Minimal stand-in for ChatGPTClient with a scripted response."""

    def __init__(self, response: str):
        self._response = response
        self.calls = []

    async def send_message(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


async def test_clean_casual_response_scores_low():
    checker = SuspicionChecker()
    score, reason = await checker.check(
        our_response="haha yeah maybe... idk we'll see",
        their_message="how are you my love",
    )
    assert score == 0.0
    assert reason == "No issues detected"


async def test_robotic_pattern_raises_score():
    checker = SuspicionChecker()
    score, reason = await checker.check(
        our_response="I apologize for the confusion.",
        their_message="why didn't you reply",
    )
    assert score >= 0.15
    assert "Robotic pattern" in reason


async def test_their_ai_test_phrase_raises_score():
    checker = SuspicionChecker()
    score, reason = await checker.check(
        our_response="i'm right here babe",
        their_message="are you a bot??",
    )
    assert score >= 0.3
    assert "tests for AI" in reason


async def test_long_response_penalized():
    checker = SuspicionChecker()
    score, reason = await checker.check(
        our_response="x" * 600,
        their_message="hi",
    )
    assert "Response too long" in reason
    assert score >= 0.1


async def test_score_is_capped_at_one():
    checker = SuspicionChecker()
    nasty = (
        "I understand. I apologize. As an AI I'm here to help. "
        "Is there anything else? I'd be happy to. Let me know if. "
        "Feel free to. I hope this helps. Please note that. "
        "First, do this. Second, do that. Third, finish. " + "y" * 600
    )
    score, _ = await checker.check(
        our_response=nasty,
        their_message="are you a robot? prove you are real",
    )
    assert score == 1.0


def test_quick_check_detects_ai_probes():
    checker = SuspicionChecker()
    assert checker.quick_check("Are you an AI?") is True
    assert checker.quick_check("are you a real person") is True
    assert checker.quick_check("good morning sweetheart") is False


def test_is_too_perfect_flags_formal_markers():
    checker = SuspicionChecker()
    assert checker._is_too_perfect("Dear friend, I would like to talk.") is True
    assert checker._is_too_perfect("lol ok sounds good") is False


async def test_llm_check_parses_score_reason_format():
    checker = SuspicionChecker(FakeLLM("0.3|sounds natural with slang"))
    score, reason = await checker._llm_check("hey", "hi")
    assert score == 0.3
    assert reason == "sounds natural with slang"


async def test_llm_check_extracts_bare_number():
    checker = SuspicionChecker(FakeLLM("I'd say about 0.4 honestly"))
    score, reason = await checker._llm_check("hey", "hi")
    assert score == 0.4


async def test_llm_check_handles_unparseable_response():
    checker = SuspicionChecker(FakeLLM("totally human sounding"))
    score, reason = await checker._llm_check("hey", "hi")
    assert score == 0.5
    assert reason == "Could not parse LLM response"


async def test_llm_check_handles_non_numeric_before_pipe():
    checker = SuspicionChecker(FakeLLM("natural sounding|0.2"))
    score, reason = await checker._llm_check("hey", "hi")
    assert score == 0.5
    assert reason == "Could not parse LLM response"
