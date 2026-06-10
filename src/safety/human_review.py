"""
Human review system for flagged conversations.
"""

import asyncio
from datetime import datetime
from typing import Optional, List

from ..core.models import Scammer, Message, ScammerStatus
from ..core.database import Database
from ..core.config import get_config
from ..utils.logging import logger, console


class HumanReviewQueue:
    """
    Manages conversations that need human review.

    When suspicion checker flags a response, it can be queued here
    for manual review before sending.

    Pause state is persisted to the database (the scammer's ``status``
    column) rather than kept only in memory, so that:

    * a pause survives a restart of the main loop, and
    * the standalone ``review_flagged.py`` tool (a separate process) can
      resume a conversation and have the running loop honour it.
    """

    def __init__(self, db: Database):
        self.db = db
        self.config = get_config()

    async def flag_for_review(
        self,
        scammer_id: str,
        message: Message,
        proposed_response: str,
        suspicion_score: float,
        reason: str
    ):
        """
        Flag a conversation for human review.

        If auto_pause is enabled, the scammer will be paused
        and no automatic responses will be sent.
        """
        # Log the suspicion
        await self.db.log_suspicion(
            scammer_id=scammer_id,
            message_id=message.id,
            score=suspicion_score,
            reason=reason
        )

        if self.config.auto_pause_on_flag:
            await self.pause(scammer_id)

        # Log to console for immediate visibility
        console.print("\n[bold red]═══ HUMAN REVIEW NEEDED ═══[/bold red]")
        console.print(f"Scammer: {scammer_id}")
        console.print(f"Their message: {message.content[:200]}...")
        console.print(f"Proposed response: {proposed_response[:200]}...")
        console.print(f"Suspicion score: {suspicion_score:.2f}")
        console.print(f"Reason: {reason}")
        console.print("[bold red]═══════════════════════════[/bold red]\n")

    async def is_paused(self, scammer_id: str) -> bool:
        """Check if a scammer's conversation is paused (reads from DB)."""
        return await self.db.get_scammer_status(scammer_id) == ScammerStatus.PAUSED

    async def resume(self, scammer_id: str):
        """Resume auto-responses for a scammer."""
        await self.db.set_scammer_status(scammer_id, ScammerStatus.ACTIVE)
        logger.info(f"Resumed auto-response for {scammer_id}")

    async def pause(self, scammer_id: str):
        """Pause auto-responses for a scammer."""
        await self.db.set_scammer_status(scammer_id, ScammerStatus.PAUSED)
        logger.warning(f"Paused auto-response for {scammer_id}")

    async def get_pending_reviews(self) -> List[dict]:
        """Get all pending human reviews."""
        flags = await self.db.get_unreviewed_flags()

        reviews = []
        for flag in flags:
            # Get the associated message
            messages = await self.db.get_messages(flag.scammer_id, limit=5)
            last_message = messages[-1] if messages else None

            reviews.append({
                "flag_id": flag.id,
                "scammer_id": flag.scammer_id,
                "score": flag.suspicion_score,
                "reason": flag.reason,
                "message": last_message.content if last_message else "N/A",
                "is_paused": await self.is_paused(flag.scammer_id),
            })

        return reviews


async def interactive_review_session(db: Database):
    """
    Run an interactive session to review flagged conversations.
    """
    queue = HumanReviewQueue(db)
    reviews = await queue.get_pending_reviews()

    if not reviews:
        console.print("[green]No pending reviews![/green]")
        return

    console.print(f"\n[bold]Found {len(reviews)} pending reviews[/bold]\n")

    for i, review in enumerate(reviews, 1):
        console.print(f"[bold cyan]═══ Review {i}/{len(reviews)} ═══[/bold cyan]")
        console.print(f"Scammer: {review['scammer_id'][:12]}...")
        console.print(f"Score: {review['score']:.2f}")
        console.print(f"Reason: {review['reason']}")
        console.print(f"Message: {review['message'][:200]}...")
        console.print(f"Status: {'PAUSED' if review['is_paused'] else 'ACTIVE'}")
        console.print()

        # Get user action
        action = input("[R]esume / [P]ause / [S]kip / [Q]uit: ").lower()

        if action == 'r':
            await queue.resume(review['scammer_id'])
            console.print("[green]Resumed[/green]")
        elif action == 'p':
            await queue.pause(review['scammer_id'])
            console.print("[yellow]Paused[/yellow]")
        elif action == 'q':
            break
        # Skip does nothing

        console.print()
