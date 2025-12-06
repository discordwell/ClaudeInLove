"""
Context window management and compression.

Implements a three-tier compression strategy:
1. Recent (last 20 messages): Full text, always included
2. Session summary (21-100): LLM-generated summary
3. Historical digest (100+): Paragraph per 50 messages
"""

from typing import List, Optional, Tuple
from datetime import datetime

from ..core.models import Message, ContextSnapshot
from ..core.database import Database
from ..utils.logging import logger


# Thresholds for compression
RECENT_WINDOW = 20
SUMMARY_THRESHOLD = 50
DIGEST_THRESHOLD = 100


class ContextManager:
    """Manages conversation context with compression."""

    def __init__(self, db: Database, llm_client=None):
        """
        Args:
            db: Database instance
            llm_client: Optional LLM client for generating summaries
        """
        self.db = db
        self.llm = llm_client

    async def get_context_for_scammer(
        self,
        scammer_id: str
    ) -> Tuple[List[Message], Optional[str]]:
        """
        Get optimized context for a scammer conversation.

        Returns:
            Tuple of (recent_messages, summary_text)
        """
        # Get total message count
        total_count = await self.db.get_message_count(scammer_id)

        # Get recent messages
        recent = await self.db.get_recent_messages(scammer_id, RECENT_WINDOW)

        # Check if we need to compress
        if total_count > SUMMARY_THRESHOLD:
            # Check for existing summary
            snapshot = await self.db.get_latest_snapshot(scammer_id)

            if snapshot and snapshot.message_range_end >= total_count - RECENT_WINDOW:
                # Summary is up to date
                return recent, snapshot.content

            # Need to generate new summary
            if self.llm and total_count > RECENT_WINDOW:
                summary = await self._generate_summary(scammer_id, total_count)
                return recent, summary

        return recent, None

    async def _generate_summary(self, scammer_id: str, total_count: int) -> str:
        """Generate a summary of older messages."""
        if not self.llm:
            return None

        try:
            # Get messages that need summarizing (excluding recent)
            older_messages = await self.db.get_messages(
                scammer_id,
                limit=total_count - RECENT_WINDOW,
                offset=RECENT_WINDOW
            )

            if not older_messages:
                return None

            # Format messages for summarization
            formatted = "\n".join([
                msg.format_for_context()
                for msg in older_messages
            ])

            # Generate summary via LLM
            prompt = f"""Summarize this romance scam conversation history. Focus on:
- Key relationship developments
- Promises or claims made by the scammer
- Any money/gift requests and our responses
- Important personal details shared

Conversation:
{formatted}

Provide a concise summary (2-3 paragraphs max):"""

            summary = await self.llm.send_message(prompt)

            # Save the snapshot
            await self.db.save_context_snapshot(
                scammer_id=scammer_id,
                snapshot_type="summary",
                content=summary,
                message_range_start=0,
                message_range_end=total_count - RECENT_WINDOW
            )

            logger.info(f"Generated context summary for {scammer_id}")
            return summary

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return None

    async def should_compress(self, scammer_id: str) -> bool:
        """Check if we should trigger compression."""
        count = await self.db.get_message_count(scammer_id)

        if count < SUMMARY_THRESHOLD:
            return False

        snapshot = await self.db.get_latest_snapshot(scammer_id)

        if not snapshot:
            return True

        # Compress if snapshot is stale (more than 20 new messages)
        messages_since = count - snapshot.message_range_end
        return messages_since > RECENT_WINDOW

    def estimate_token_count(self, text: str) -> int:
        """Rough estimate of token count (4 chars per token)."""
        return len(text) // 4

    async def get_compressed_context(
        self,
        scammer_id: str,
        max_tokens: int = 4000
    ) -> Tuple[List[Message], Optional[str]]:
        """
        Get context that fits within token budget.

        Args:
            scammer_id: The scammer ID
            max_tokens: Maximum tokens for context

        Returns:
            Tuple of (messages, summary) that fit within budget
        """
        messages, summary = await self.get_context_for_scammer(scammer_id)

        # Estimate current size
        context_text = "\n".join(m.format_for_context() for m in messages)
        if summary:
            context_text = summary + "\n" + context_text

        current_tokens = self.estimate_token_count(context_text)

        # Reduce if needed
        while current_tokens > max_tokens and len(messages) > 5:
            messages = messages[1:]  # Remove oldest
            context_text = "\n".join(m.format_for_context() for m in messages)
            if summary:
                context_text = summary + "\n" + context_text
            current_tokens = self.estimate_token_count(context_text)

        return messages, summary
