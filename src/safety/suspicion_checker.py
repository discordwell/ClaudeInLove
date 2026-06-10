"""
Suspicion checker - detects if scammer might suspect they're talking to an AI.
"""

import re
from typing import Tuple, Optional, TYPE_CHECKING

from ..llm.prompt_builder import build_suspicion_check_prompt
from ..core.config import get_config
from ..utils.logging import logger, log_suspicion

if TYPE_CHECKING:
    # Imported only for type hints; avoids pulling the Playwright browser
    # stack into modules (and tests) that only need the suspicion logic.
    from ..llm.chatgpt_client import ChatGPTClient


class SuspicionChecker:
    """
    Checks outgoing messages for signs that might trigger AI suspicion.

    Uses the same ChatGPT instance to evaluate responses before sending.
    """

    # Patterns that often indicate robotic responses
    ROBOTIC_PATTERNS = [
        r"I understand\.",
        r"I apologize",
        r"As an AI",
        r"I'm here to help",
        r"Is there anything else",
        r"I'd be happy to",
        r"Let me know if",
        r"Feel free to",
        r"I hope this helps",
        r"Please note that",
        r"\d+\.\s+\w+\n\d+\.\s+\w+",  # Numbered lists
        r"First,.*Second,.*Third,",  # Sequential markers
    ]

    # Questions that might be tests for AI
    AI_TEST_PHRASES = [
        r"are you (a |an )?(robot|bot|ai|artificial|chatgpt|gpt|computer)",
        r"you('re| are) (a |an )?(robot|bot|ai|machine)",
        r"this is (a |an )?(bot|ai|automated)",
        r"talking to (a |an )?(bot|ai|robot)",
        r"real person",
        r"human or",
        r"prove you('re| are)",
        r"captcha|turing",
    ]

    def __init__(self, llm_client: "Optional[ChatGPTClient]" = None):
        """
        Args:
            llm_client: Optional ChatGPT client for advanced checking
        """
        self.llm = llm_client
        self.config = get_config()

    async def check(
        self,
        our_response: str,
        their_message: str,
        scammer_id: str = None
    ) -> Tuple[float, str]:
        """
        Check if our response might raise AI suspicion.

        Args:
            our_response: The response we're about to send
            their_message: The scammer's message we're responding to
            scammer_id: Optional scammer ID for logging

        Returns:
            Tuple of (suspicion_score, reason)
            Score is 0.0-1.0, higher = more suspicious
        """
        reasons = []
        base_score = 0.0

        # Check for robotic patterns in our response
        for pattern in self.ROBOTIC_PATTERNS:
            if re.search(pattern, our_response, re.IGNORECASE):
                base_score += 0.15
                reasons.append(f"Robotic pattern: {pattern[:20]}...")

        # Check if their message might be testing for AI
        for pattern in self.AI_TEST_PHRASES:
            if re.search(pattern, their_message, re.IGNORECASE):
                base_score += 0.3
                reasons.append("Their message tests for AI")

        # Check response length (too long can seem robotic)
        if len(our_response) > 500:
            base_score += 0.1
            reasons.append("Response too long")

        # Check for too-perfect grammar/punctuation
        if self._is_too_perfect(our_response):
            base_score += 0.1
            reasons.append("Too perfect grammar")

        # Use LLM for deeper check if available and score is borderline
        if self.llm and 0.3 <= base_score <= 0.7:
            try:
                llm_score, llm_reason = await self._llm_check(our_response, their_message)
                # Average the scores
                final_score = (base_score + llm_score) / 2
                if llm_reason:
                    reasons.append(f"LLM: {llm_reason}")
            except Exception as e:
                logger.warning(f"LLM check failed: {e}")
                final_score = base_score
        else:
            final_score = base_score

        # Cap at 1.0
        final_score = min(final_score, 1.0)

        reason = "; ".join(reasons) if reasons else "No issues detected"

        # Log if above threshold
        if final_score >= self.config.suspicion_threshold:
            log_suspicion(scammer_id or "unknown", our_response, final_score, reason)

        return final_score, reason

    def _is_too_perfect(self, text: str) -> bool:
        """Check if text has suspiciously perfect grammar."""
        # Humans make typos, use contractions inconsistently, etc.

        # Check for overly formal patterns
        formal_markers = [
            r"^Dear ",
            r"^Hello,",
            r"Sincerely,",
            r"Best regards,",
            r"I would like to",
            r"I am writing to",
        ]

        for pattern in formal_markers:
            if re.search(pattern, text):
                return True

        # Check sentence structure (too uniform = suspicious)
        sentences = re.split(r'[.!?]+', text)
        if len(sentences) > 3:
            lengths = [len(s.strip()) for s in sentences if s.strip()]
            if lengths:
                avg_len = sum(lengths) / len(lengths)
                variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
                # Low variance = too uniform
                if variance < 100:
                    return True

        return False

    async def _llm_check(self, our_response: str, their_message: str) -> Tuple[float, str]:
        """Use LLM to check for AI-like patterns."""
        prompt = build_suspicion_check_prompt(our_response, their_message)

        try:
            result = await self.llm.send_message(prompt)

            # Parse SCORE|REASON format
            if "|" in result:
                parts = result.split("|", 1)
                score = float(parts[0].strip())
                reason = parts[1].strip() if len(parts) > 1 else ""
                return score, reason
            else:
                # Try to extract just a number
                match = re.search(r'(0\.\d+|1\.0|0|1)', result)
                if match:
                    return float(match.group(1)), result[:100]

        except Exception as e:
            logger.warning(f"Error parsing LLM check result: {e}")

        return 0.5, "Could not parse LLM response"

    def quick_check(self, their_message: str) -> bool:
        """
        Quick check if their message is testing for AI.
        Returns True if we should be extra careful.
        """
        for pattern in self.AI_TEST_PHRASES:
            if re.search(pattern, their_message, re.IGNORECASE):
                return True
        return False
