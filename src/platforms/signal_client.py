"""
Signal Desktop client using Chrome DevTools Protocol (CDP).

Signal Desktop is an Electron app that supports remote debugging.
Launch Signal with: signal-desktop --remote-debugging-port=9222
Then we connect via CDP to automate it.
"""

import asyncio
import re
from typing import List, Optional, Set
from datetime import datetime

from playwright.async_api import async_playwright, Page, CDPSession

from .base import PlatformClient
from ..core.models import IncomingMessage, Platform
from ..core.config import get_config
from ..utils.logging import logger, log_message


class SignalClient(PlatformClient):
    """
    Signal Desktop automation via CDP.

    Requires Signal Desktop to be running with:
        signal-desktop --remote-debugging-port=9222
    """

    platform = Platform.SIGNAL

    def __init__(self, debug_port: int = None):
        config = get_config()
        self.debug_port = debug_port or config.signal_debug_port
        self.cdp_url = f"http://localhost:{self.debug_port}"

        self._playwright = None
        self._browser = None
        self._page: Optional[Page] = None
        self._cdp: Optional[CDPSession] = None

        # Track seen messages to avoid duplicates
        self._seen_message_ids: Set[str] = set()
        self._last_check: datetime = datetime.now()

    async def connect(self):
        """Connect to Signal Desktop via CDP."""
        logger.info(f"Connecting to Signal Desktop at {self.cdp_url}...")

        self._playwright = await async_playwright().start()

        try:
            # Connect to existing Signal Desktop instance
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)

            # Get the default context and page
            contexts = self._browser.contexts
            if not contexts:
                raise RuntimeError("No browser contexts found. Is Signal Desktop running?")

            context = contexts[0]
            pages = context.pages
            if not pages:
                raise RuntimeError("No pages found in Signal Desktop.")

            self._page = pages[0]
            self._cdp = await self._page.context.new_cdp_session(self._page)

            logger.info("Connected to Signal Desktop successfully!")

            # Wait for Signal UI to be ready
            await self._wait_for_signal_ui()

        except Exception as e:
            logger.error(f"Failed to connect to Signal Desktop: {e}")
            logger.info("Make sure Signal Desktop is running with: signal-desktop --remote-debugging-port=9222")
            raise

    async def _wait_for_signal_ui(self, timeout: int = 30):
        """Wait for Signal's main UI to load."""
        logger.info("Waiting for Signal UI to be ready...")

        try:
            # Wait for the conversation list to appear
            await self._page.wait_for_selector(
                '.module-conversation-list, .ConversationList, [data-testid="ConversationList"]',
                timeout=timeout * 1000
            )
            logger.info("Signal UI is ready")
        except Exception:
            # Signal UI might have different selectors depending on version
            logger.warning("Could not find standard Signal UI elements. Continuing anyway...")

    async def disconnect(self):
        """Disconnect from Signal Desktop."""
        if self._browser:
            # Don't close Signal - just disconnect from it
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Disconnected from Signal Desktop")

    async def get_conversations(self) -> List[str]:
        """Get list of conversation IDs (phone numbers)."""
        conversations = []

        try:
            # Find all conversation items
            items = await self._page.query_selector_all(
                '.module-conversation-list-item, [data-testid^="conversation-"]'
            )

            for item in items:
                # Try to extract phone number or contact name
                data_id = await item.get_attribute('data-id')
                if data_id:
                    conversations.append(data_id)
                else:
                    # Try to get from inner text
                    text = await item.inner_text()
                    # Look for phone number pattern
                    phone_match = re.search(r'\+?\d{10,15}', text)
                    if phone_match:
                        conversations.append(phone_match.group())

        except Exception as e:
            logger.error(f"Error getting conversations: {e}")

        return conversations

    async def get_new_messages(self) -> List[IncomingMessage]:
        """
        Get new unread messages from Signal.
        Polls the UI for unread indicators and new messages.
        """
        new_messages = []

        try:
            # Look for conversations with unread indicators
            unread_items = await self._page.query_selector_all(
                '.module-conversation-list-item--has-unread, [data-testid*="unread"]'
            )

            for item in unread_items:
                # Click to open conversation
                await item.click()
                await asyncio.sleep(0.5)  # Wait for conversation to load

                # Get messages from the conversation
                messages = await self._extract_messages_from_conversation()
                new_messages.extend(messages)

        except Exception as e:
            logger.error(f"Error getting new messages: {e}")

        return new_messages

    async def _extract_messages_from_conversation(self) -> List[IncomingMessage]:
        """Extract messages from the currently open conversation."""
        messages = []

        try:
            # Get conversation header for sender info
            header = await self._page.query_selector(
                '.module-conversation-header, [data-testid="conversation-header"]'
            )
            sender_name = None
            sender_id = None

            if header:
                sender_name = await header.inner_text()
                # Try to extract phone number
                phone_match = re.search(r'\+?\d{10,15}', sender_name)
                if phone_match:
                    sender_id = phone_match.group()
                else:
                    sender_id = sender_name.strip()

            # Get message elements
            message_elements = await self._page.query_selector_all(
                '.module-message--incoming, [data-testid="incoming-message"]'
            )

            for elem in message_elements[-5:]:  # Only check last 5 messages
                try:
                    # Get message text
                    text_elem = await elem.query_selector(
                        '.module-message__text, [data-testid="message-text"]'
                    )
                    if not text_elem:
                        continue

                    content = await text_elem.inner_text()

                    # Get message ID (timestamp or data attribute)
                    msg_id = await elem.get_attribute('data-id')
                    if not msg_id:
                        # Use content hash as ID
                        msg_id = str(hash(content + str(datetime.now().timestamp())))

                    # Skip if we've seen this message
                    if msg_id in self._seen_message_ids:
                        continue

                    self._seen_message_ids.add(msg_id)

                    message = IncomingMessage(
                        platform=Platform.SIGNAL,
                        sender_id=sender_id or "unknown",
                        sender_name=sender_name,
                        content=content,
                        platform_message_id=msg_id,
                    )
                    messages.append(message)
                    log_message("inbound", sender_id or "unknown", content)

                except Exception as e:
                    logger.debug(f"Error extracting message: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error extracting messages: {e}")

        return messages

    async def send_message(self, recipient_id: str, content: str) -> bool:
        """
        Send a message to a recipient.

        Args:
            recipient_id: Phone number (with or without +)
            content: Message text
        """
        try:
            # First, try to find and click on the conversation
            conversation_found = await self._find_and_open_conversation(recipient_id)

            if not conversation_found:
                logger.error(f"Could not find conversation with {recipient_id}")
                return False

            # Find the message input
            input_selector = (
                '.module-composition-input, '
                '[data-testid="CompositionInput"], '
                '.ql-editor, '
                'div[contenteditable="true"]'
            )

            input_elem = await self._page.wait_for_selector(input_selector, timeout=5000)
            if not input_elem:
                logger.error("Could not find message input")
                return False

            # Click and type the message
            await input_elem.click()
            await asyncio.sleep(0.2)

            # Type with some human-like delays
            for char in content:
                await self._page.keyboard.type(char)
                await asyncio.sleep(0.02)  # Small delay between chars

            await asyncio.sleep(0.3)

            # Find and click send button, or press Enter
            send_btn = await self._page.query_selector(
                '.module-composition-area__send-button, '
                '[data-testid="send-button"], '
                'button[aria-label="Send"]'
            )

            if send_btn:
                await send_btn.click()
            else:
                await self._page.keyboard.press('Enter')

            await asyncio.sleep(0.5)
            log_message("outbound", recipient_id, content)
            logger.info(f"Sent message to {recipient_id}")
            return True

        except Exception as e:
            logger.error(f"Error sending message to {recipient_id}: {e}")
            return False

    async def _find_and_open_conversation(self, recipient_id: str) -> bool:
        """Find and open a conversation by recipient ID."""
        try:
            # Normalize phone number
            normalized = self._normalize_phone(recipient_id)

            # Try to find in conversation list
            items = await self._page.query_selector_all('.module-conversation-list-item')

            for item in items:
                item_text = await item.inner_text()

                # Check if this conversation matches
                if normalized in item_text or recipient_id in item_text:
                    await item.click()
                    await asyncio.sleep(0.5)
                    return True

            # Try using Signal's search
            search_input = await self._page.query_selector(
                '.module-main-header__search-input, '
                '[data-testid="search-input"]'
            )

            if search_input:
                await search_input.click()
                await search_input.fill(recipient_id)
                await asyncio.sleep(1)

                # Click first result
                first_result = await self._page.query_selector(
                    '.module-conversation-list-item'
                )
                if first_result:
                    await first_result.click()
                    await asyncio.sleep(0.5)
                    return True

            return False

        except Exception as e:
            logger.error(f"Error finding conversation: {e}")
            return False

    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number to E.164 format."""
        # Remove all non-digits except +
        cleaned = re.sub(r'[^\d+]', '', phone)

        # Add + if not present and looks like US number
        if not cleaned.startswith('+') and len(cleaned) == 10:
            cleaned = '+1' + cleaned
        elif not cleaned.startswith('+'):
            cleaned = '+' + cleaned

        return cleaned
