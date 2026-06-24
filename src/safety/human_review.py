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
        reason: str,
        force_pause: bool = False
    ):
        """
        Flag a conversation for human review.

        The conversation is paused (so no automatic responses go out) when
        ``auto_pause_on_flag`` is enabled **or** ``force_pause`` is set.
        ``force_pause`` is for hard-safety violations (the reply would send
        money or leak PII): those must always be held no matter how the
        operator configured auto-pause, since sending one is the exact outcome
        the tool exists to prevent.
        """
        # Log the suspicion, keeping the withheld reply so a human reviewer
        # can see exactly what the bot wanted to send before deciding.
        await self.db.log_suspicion(
            scammer_id=scammer_id,
            message_id=message.id,
            score=suspicion_score,
            reason=reason,
            proposed_response=proposed_response,
        )

        if self.config.auto_pause_on_flag or force_pause:
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

    async def mark_reviewed(self, flag_id: int):
        """
        Record that a human has acted on a flagged reply so it leaves the queue.

        ``get_pending_reviews`` reads from ``get_unreviewed_flags``; until a flag
        is marked reviewed it keeps reappearing every time the review tool runs.
        """
        await self.db.mark_flag_reviewed(flag_id)
        logger.info(f"Marked suspicion flag {flag_id} as reviewed")

    async def resume(self, scammer_id: str):
        """Resume auto-responses for a scammer."""
        await self.db.set_scammer_status(scammer_id, ScammerStatus.ACTIVE)
        logger.info(f"Resumed auto-response for {scammer_id}")

    async def pause(self, scammer_id: str):
        """Pause auto-responses for a scammer."""
        await self.db.set_scammer_status(scammer_id, ScammerStatus.PAUSED)
        logger.warning(f"Paused auto-response for {scammer_id}")

    async def archive(self, scammer_id: str):
        """
        Retire a conversation for good.

        Unlike :meth:`pause` (a temporary hold for review), archiving marks a
        conversation as finished — the scammer caught on, went silent, or the
        operator is simply done with them. The main loop only auto-responds to
        ``ACTIVE`` conversations, so an archived one is never answered again
        unless it is explicitly resumed.
        """
        await self.db.set_scammer_status(scammer_id, ScammerStatus.ARCHIVED)
        logger.info(f"Archived conversation with {scammer_id}")

    async def add_note(self, scammer_id: str, note: str) -> str:
        """
        Append a free-text note to a scammer and return the combined notes.

        Notes accumulate (newline-separated) so observations gathered across
        several review sessions are all preserved, and they are not just a paper
        trail: ``build_full_prompt`` injects them into every subsequent reply as
        ``[Notes about this scammer: ...]``, so a note like "claims to be an
        oil-rig engineer named David" actually steers the persona's future
        answers. A blank/whitespace note is ignored (returns the existing notes
        unchanged) so an accidental empty entry never adds a stray blank line.

        Unlike resume/pause/archive, taking a note is **not** a review decision:
        it does not touch the scammer's status or mark any flag reviewed.
        """
        note = (note or "").strip()
        existing = await self.db.get_scammer_notes(scammer_id)
        if not note:
            return existing or ""

        combined = f"{existing}\n{note}" if existing else note
        await self.db.set_scammer_notes(scammer_id, combined)
        logger.info(f"Added note for {scammer_id}")
        return combined

    async def get_pending_reviews(self) -> List[dict]:
        """Get all pending human reviews."""
        flags = await self.db.get_unreviewed_flags()

        reviews = []
        for flag in flags:
            # Show the message the flag was actually raised against, not merely
            # the most recent one. With auto_pause disabled an outbound reply is
            # stored after the flag, and a scammer can have several flags at
            # once, so "the latest message" is frequently the wrong one (and may
            # be our own reply). Look it up by the flag's recorded message id.
            flagged_message = (
                await self.db.get_message_by_id(flag.message_id)
                if flag.message_id
                else None
            )

            # Report the conversation's actual lifecycle status (active / paused
            # / archived) rather than only a paused/active boolean, so the
            # reviewer can tell, say, an archived conversation from a live one.
            status = await self.db.get_scammer_status(flag.scammer_id)

            # Surface any operator notes so the reviewer sees the context that is
            # already steering the persona's replies, and can build on it.
            notes = await self.db.get_scammer_notes(flag.scammer_id)

            reviews.append({
                "flag_id": flag.id,
                "scammer_id": flag.scammer_id,
                "score": flag.suspicion_score,
                "reason": flag.reason,
                "message": flagged_message.content if flagged_message else "N/A",
                "proposed_response": flag.proposed_response,
                "status": status.value if status else "unknown",
                "is_paused": status == ScammerStatus.PAUSED,
                "notes": notes,
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

    quit_requested = False
    for i, review in enumerate(reviews, 1):
        console.print(f"[bold cyan]═══ Review {i}/{len(reviews)} ═══[/bold cyan]")
        console.print(f"Scammer: {review['scammer_id'][:12]}...")
        console.print(f"Score: {review['score']:.2f}")
        console.print(f"Reason: {review['reason']}")
        console.print(f"Their message: {review['message'][:200]}...")
        console.print(
            f"Proposed reply (withheld): {review['proposed_response'] or 'N/A'}"
        )
        console.print(f"Status: {review['status'].upper()}")
        if review.get("notes"):
            console.print(f"Notes: {review['notes']}")
        console.print()

        # Loop on this one flag until a terminal action is taken. Resume, Pause
        # and Archive are all decisions, so they handle the flag (mark it
        # reviewed → it won't resurface next run) and move on. Taking a Note is
        # *not* a decision: it annotates the conversation and re-prompts so the
        # operator still chooses what to do with the flag. Skip leaves it
        # pending; Quit stops without touching the remaining flags.
        while True:
            action = input(
                "[R]esume / [P]ause / [A]rchive / [N]ote / [S]kip / [Q]uit: "
            ).lower()

            if action == 'r':
                await queue.resume(review['scammer_id'])
                await queue.mark_reviewed(review['flag_id'])
                console.print("[green]Resumed[/green]")
                break
            elif action == 'p':
                await queue.pause(review['scammer_id'])
                await queue.mark_reviewed(review['flag_id'])
                console.print("[yellow]Paused[/yellow]")
                break
            elif action == 'a':
                await queue.archive(review['scammer_id'])
                await queue.mark_reviewed(review['flag_id'])
                console.print("[dim]Archived[/dim]")
                break
            elif action == 'n':
                note = input("Note (blank to cancel): ").strip()
                if note:
                    review['notes'] = await queue.add_note(
                        review['scammer_id'], note
                    )
                    console.print("[blue]Note added[/blue]")
                else:
                    console.print("[dim]No note added[/dim]")
                # Re-prompt: the flag still needs a decision.
                continue
            elif action == 'q':
                quit_requested = True
                break
            else:
                # Skip (or any unrecognized key): leave the flag pending and
                # advance to the next review.
                break

        if quit_requested:
            break

        console.print()
