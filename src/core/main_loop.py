"""
Main orchestration loop for ClaudeInLove.
"""

import asyncio
import random
import signal
from typing import Optional

from rich.console import Console
from rich.panel import Panel

from .config import get_config
from .database import Database
from .models import MessageDirection, IncomingMessage

from ..platforms.signal_client import SignalClient
from ..llm.chatgpt_client import ChatGPTClient
from ..llm.prompt_builder import build_full_prompt
from ..llm.context_manager import ContextManager
from ..persona.persona_builder import load_or_create_persona, create_default_persona
from ..safety.suspicion_checker import SuspicionChecker
from ..safety.human_review import HumanReviewQueue
from ..utils.logging import logger, log_message, log_status, log_error

console = Console()


class ClaudeInLove:
    """
    Main application class.

    Orchestrates:
    - Signal message monitoring
    - ChatGPT response generation
    - Suspicion checking
    - Human review flagging
    """

    def __init__(self):
        self.config = get_config()
        self.db: Optional[Database] = None
        self.signal: Optional[SignalClient] = None
        self.chatgpt: Optional[ChatGPTClient] = None
        self.context_manager: Optional[ContextManager] = None
        self.suspicion_checker: Optional[SuspicionChecker] = None
        self.review_queue: Optional[HumanReviewQueue] = None
        self.persona = None

        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Initialize all components."""
        console.print(Panel.fit(
            "[bold magenta]ClaudeInLove[/bold magenta]\n"
            "[dim]Romance Scam Baiting Automation[/dim]",
            border_style="magenta"
        ))

        log_status("Initializing components...")

        # Database
        self.db = Database()
        await self.db.connect()
        log_status("Database connected")

        # Load or create persona
        self.persona = await load_or_create_persona(self.db)
        if not self.persona:
            log_status("No persona found, using default")
            self.persona = create_default_persona()
            await self.db.save_persona(self.persona)
        log_status(f"Loaded persona: {self.persona.name}")

        # ChatGPT client
        self.chatgpt = ChatGPTClient()
        await self.chatgpt.connect()
        log_status("ChatGPT client connected")

        # Context manager
        self.context_manager = ContextManager(self.db, self.chatgpt)

        # Suspicion checker
        self.suspicion_checker = SuspicionChecker(self.chatgpt)

        # Human review queue
        self.review_queue = HumanReviewQueue(self.db)

        # Signal client
        self.signal = SignalClient()
        try:
            await self.signal.connect()
            log_status("Signal client connected")
        except Exception as e:
            log_error(f"Signal connection failed: {e}")
            log_status("Run Signal Desktop with: signal-desktop --remote-debugging-port=9222")
            raise

        self._running = True
        log_status("All components ready!")

    async def stop(self):
        """Shutdown all components."""
        log_status("Shutting down...")
        self._running = False
        self._shutdown_event.set()

        if self.signal:
            await self.signal.disconnect()
        if self.chatgpt:
            await self.chatgpt.disconnect()
        if self.db:
            await self.db.close()

        log_status("Shutdown complete")

    async def run(self):
        """Main loop."""
        try:
            await self.start()

            log_status("Starting main loop (Ctrl+C to stop)...")
            console.print()

            while self._running:
                try:
                    # Check for new messages
                    messages = await self.signal.get_new_messages()

                    for msg in messages:
                        await self.handle_incoming_message(msg)

                    # Small delay between checks
                    await asyncio.sleep(5)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log_error(f"Error in main loop: {e}", e)
                    await asyncio.sleep(10)  # Back off on error

        finally:
            await self.stop()

    async def handle_incoming_message(self, msg: IncomingMessage):
        """Process an incoming message and generate response."""
        try:
            # Get or create scammer record
            scammer = await self.db.get_or_create_scammer(
                platform=msg.platform,
                platform_id=msg.sender_id,
                display_name=msg.sender_name,
            )

            # Check if paused for human review
            if await self.review_queue.is_paused(scammer.id):
                log_status(f"Skipping {scammer.id} (paused for review)")
                return

            # Durable dedup: the platform client's in-memory seen-set is lost on
            # restart, so fall back to the messages table — the persistent record
            # of what we have already handled — to avoid answering the same
            # message twice. Only applied to real, unique platform ids; content
            # fingerprints (synthetic_id) collide for repeated text and so are
            # left to the per-session seen-set.
            if (
                msg.platform_message_id
                and not msg.synthetic_id
                and await self.db.has_inbound_message(
                    scammer.id, msg.platform_message_id
                )
            ):
                log_status(f"Skipping duplicate message from {scammer.id[:8]}")
                return

            # Store incoming message
            stored_msg = await self.db.add_message(
                scammer_id=scammer.id,
                direction=MessageDirection.INBOUND,
                content=msg.content,
                platform_message_id=msg.platform_message_id,
            )

            # Quick check if they're probing for an AI ("are you a bot?").
            # An active probe is exactly the moment a human should look, so it
            # forces a review below even when the drafted reply scores low on
            # its own.
            is_ai_probe = self.suspicion_checker.quick_check(msg.content)
            if is_ai_probe:
                log_status(f"AI test detected from {scammer.id[:8]}")

            # Get conversation context
            messages, summary = await self.context_manager.get_compressed_context(
                scammer.id, max_tokens=3000
            )

            # Build prompt
            prompt = build_full_prompt(
                incoming_message=msg.content,
                persona=self.persona,
                messages=messages,
                summary=summary,
                scammer=scammer,
            )

            # Generate response via ChatGPT
            log_status(f"Generating response for {scammer.id[:8]}...")
            response = await self.chatgpt.send_message(prompt)

            if not response:
                log_error("Empty response from ChatGPT")
                return

            # Check suspicion before sending
            score, reason = await self.suspicion_checker.check(
                our_response=response,
                their_message=msg.content,
                scammer_id=scammer.id,
            )

            # Flag for human review when the drafted reply looks AI-ish OR the
            # scammer is actively probing for a bot.
            should_review = score >= self.config.suspicion_threshold or is_ai_probe
            if should_review:
                if is_ai_probe and score < self.config.suspicion_threshold:
                    reason = f"{reason}; AI probe in their message"

                await self.review_queue.flag_for_review(
                    scammer_id=scammer.id,
                    message=stored_msg,
                    proposed_response=response,
                    suspicion_score=score,
                    reason=reason,
                )

                if self.config.auto_pause_on_flag:
                    log_status("Response withheld pending human review")
                    return

            # Add human-like delay before responding
            delay = random.uniform(
                self.config.min_response_delay,
                self.config.max_response_delay
            )
            log_status(f"Waiting {delay:.0f}s before responding...")
            await asyncio.sleep(delay)

            # Send response
            success = await self.signal.send_message(msg.sender_id, response)

            if success:
                # Store outgoing message
                await self.db.add_message(
                    scammer_id=scammer.id,
                    direction=MessageDirection.OUTBOUND,
                    content=response,
                    was_flagged=should_review,
                    flag_reason=reason if should_review else None,
                )
                log_message("outbound", scammer.id, response)
            else:
                log_error(f"Failed to send message to {msg.sender_id}")

            # Check if we should compress context
            if await self.context_manager.should_compress(scammer.id):
                log_status(f"Compressing context for {scammer.id[:8]}...")
                await self.context_manager.get_context_for_scammer(scammer.id)

        except Exception as e:
            log_error(f"Error handling message: {e}", e)


def request_shutdown(app: ClaudeInLove):
    """Signal the main loop to stop and shut down gracefully."""
    console.print("\n[yellow]Received shutdown signal...[/yellow]")
    app._running = False
    app._shutdown_event.set()


def setup_signal_handlers(app: ClaudeInLove):
    """
    Register graceful-shutdown handlers on the running event loop.

    Using the loop's ``add_signal_handler`` (instead of ``signal.signal``
    plus ``sys.exit``) lets the main loop break out cleanly and run
    :meth:`ClaudeInLove.stop`, so the database and browser are closed
    properly. Falls back silently on platforms without loop signal support
    (e.g. Windows), where the ``KeyboardInterrupt`` path still applies.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown, app)
        except (NotImplementedError, RuntimeError):
            pass


async def async_main():
    """Async entry point."""
    app = ClaudeInLove()
    setup_signal_handlers(app)
    await app.run()


def main():
    """Entry point."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        raise


if __name__ == "__main__":
    main()
