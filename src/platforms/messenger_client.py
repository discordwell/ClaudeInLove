"""
Facebook Messenger client using browser automation.

Uses Playwright to automate messenger.com with stealth measures
to avoid detection and maintain persistent login sessions.
"""

import asyncio
import re
from typing import List, Optional, Set
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from .base import PlatformClient
from ..core.models import IncomingMessage, Platform
from ..core.config import get_config
from ..utils.browser import PersistentBrowser
from ..utils.logging import logger, log_message


class MessengerClient(PlatformClient):
    """
    Facebook Messenger automation via browser.

    Uses persistent browser sessions to maintain Facebook login.
    First run will require manual login, subsequent runs reuse session.
    """

    platform = Platform.MESSENGER
    MESSENGER_URL = "https://www.messenger.com"

    def __init__(self, headless: bool = None):
        config = get_config()
        self.headless = headless if headless is not None else config.browser_headless

        # Use dedicated profile dir for Messenger
        self.profile_dir = config.data_dir / "messenger_profile"

        self._browser: Optional[PersistentBrowser] = None
        self._page: Optional[Page] = None

        # Track seen messages to avoid duplicates
        self._seen_message_ids: Set[str] = set()
        self._current_conversation_id: Optional[str] = None

    async def connect(self):
        """Connect to Messenger via browser."""
        logger.info("Launching browser for Messenger...")

        self._browser = PersistentBrowser(
            headless=self.headless,
            user_data_dir=self.profile_dir,
        )
        self._page = await self._browser.start()

        # Navigate to Messenger
        logger.info(f"Navigating to {self.MESSENGER_URL}...")
        await self._page.goto(self.MESSENGER_URL, wait_until="networkidle")

        # Check if logged in
        if await self._is_logged_in():
            logger.info("Already logged in to Messenger!")
        else:
            logger.info("Not logged in. Please log in manually...")
            await self._wait_for_login()

        # Wait for chat list to load
        await self._wait_for_chat_list()
        logger.info("Connected to Messenger successfully!")

    async def _is_logged_in(self) -> bool:
        """Check if we're logged in to Messenger."""
        try:
            # Look for chat list or compose button (signs of being logged in)
            logged_in_indicators = [
                '[aria-label="Chats"]',
                '[aria-label="New message"]',
                '[data-testid="mwthreadlist-item"]',
                'div[role="navigation"]',
            ]

            for selector in logged_in_indicators:
                element = await self._page.query_selector(selector)
                if element:
                    return True

            # Check for login form (sign we're not logged in)
            login_form = await self._page.query_selector('input[name="email"], input[name="pass"]')
            if login_form:
                return False

            # Check URL
            if "login" in self._page.url.lower():
                return False

            return False
        except Exception as e:
            logger.debug(f"Error checking login status: {e}")
            return False

    async def _wait_for_login(self, timeout: int = 300):
        """Wait for user to complete manual login."""
        logger.info("Waiting for manual login (5 minute timeout)...")
        logger.info("Please log in to Facebook/Messenger in the browser window.")

        start_time = datetime.now()
        while (datetime.now() - start_time).seconds < timeout:
            if await self._is_logged_in():
                logger.info("Login detected!")
                return
            await asyncio.sleep(2)

        raise TimeoutError("Login timeout - please try again")

    async def _wait_for_chat_list(self, timeout: int = 30):
        """Wait for the chat list to load."""
        logger.info("Waiting for chat list to load...")

        selectors = [
            '[aria-label="Chats"]',
            '[data-testid="mwthreadlist-item"]',
            'div[role="row"]',
            '[aria-label="Conversation list"]',
        ]

        for selector in selectors:
            try:
                await self._page.wait_for_selector(selector, timeout=timeout * 1000)
                logger.info("Chat list loaded")
                return
            except PlaywrightTimeout:
                continue

        logger.warning("Could not confirm chat list loaded, continuing anyway...")

    async def disconnect(self):
        """Disconnect from Messenger."""
        if self._browser:
            await self._browser.close()
        logger.info("Disconnected from Messenger")

    async def get_conversations(self) -> List[str]:
        """Get list of conversation IDs."""
        conversations = []

        try:
            # Find all conversation items in the sidebar
            conv_selectors = [
                '[data-testid="mwthreadlist-item"]',
                'div[role="row"][tabindex="0"]',
                'a[href*="/t/"]',
            ]

            for selector in conv_selectors:
                items = await self._page.query_selector_all(selector)
                if items:
                    break

            for item in items:
                try:
                    # Try to get conversation ID from href or data attribute
                    href = await item.get_attribute('href')
                    if href and '/t/' in href:
                        # Extract ID from URL like /t/123456789
                        match = re.search(r'/t/(\d+)', href)
                        if match:
                            conversations.append(match.group(1))
                            continue

                    # Try data-testid
                    data_id = await item.get_attribute('data-testid')
                    if data_id:
                        conversations.append(data_id)
                        continue

                    # Try to find link inside
                    link = await item.query_selector('a[href*="/t/"]')
                    if link:
                        href = await link.get_attribute('href')
                        match = re.search(r'/t/(\d+)', href)
                        if match:
                            conversations.append(match.group(1))

                except Exception as e:
                    logger.debug(f"Error extracting conversation ID: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error getting conversations: {e}")

        return list(set(conversations))  # Dedupe

    async def get_new_messages(self) -> List[IncomingMessage]:
        """Get new unread messages from Messenger."""
        new_messages = []

        try:
            # Look for conversations with unread indicators
            unread_selectors = [
                # Blue dot or unread count
                '[data-testid="mwthreadlist-item"]:has([aria-label*="unread"])',
                '[data-testid="mwthreadlist-item"]:has([data-testid="unread-indicator"])',
                'div[role="row"]:has([aria-label*="unread"])',
                # Bold text (unread)
                'div[role="row"]:has(span[style*="font-weight: bold"])',
            ]

            unread_items = []
            for selector in unread_selectors:
                try:
                    items = await self._page.query_selector_all(selector)
                    if items:
                        unread_items = items
                        break
                except Exception:
                    continue

            if not unread_items:
                # Fallback: check first few conversations
                items = await self._page.query_selector_all('[data-testid="mwthreadlist-item"]')
                unread_items = items[:3] if items else []

            for item in unread_items:
                try:
                    await item.click()
                    await asyncio.sleep(1)  # Wait for conversation to load

                    # Extract messages from this conversation
                    messages = await self._extract_messages_from_conversation()
                    new_messages.extend(messages)

                except Exception as e:
                    logger.debug(f"Error processing conversation: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error getting new messages: {e}")

        return new_messages

    async def _extract_messages_from_conversation(self) -> List[IncomingMessage]:
        """Extract messages from the currently open conversation."""
        messages = []

        try:
            # Get sender info from conversation header
            sender_name = await self._get_conversation_name()
            sender_id = await self._get_conversation_id()

            if not sender_id:
                sender_id = sender_name or "unknown"

            # Get incoming message elements (messages from the other person)
            # Messenger marks incoming messages differently than outgoing
            message_selectors = [
                # Messages not from self (incoming)
                'div[dir="auto"][class*="message"]:not([class*="outgoing"])',
                # Generic message containers
                'div[role="row"] div[dir="auto"]',
                # Text content in message bubbles
                'div[data-scope="messages_table"] div[dir="auto"]',
            ]

            message_elements = []
            for selector in message_selectors:
                try:
                    elements = await self._page.query_selector_all(selector)
                    if elements:
                        message_elements = elements[-10:]  # Last 10 messages
                        break
                except Exception:
                    continue

            for elem in message_elements:
                try:
                    content = await elem.inner_text()
                    content = content.strip()

                    if not content or len(content) < 1:
                        continue

                    # Skip if it looks like a system message
                    if self._is_system_message(content):
                        continue

                    # Generate message ID from content hash
                    msg_id = str(hash(f"{sender_id}:{content}"))

                    # Skip if we've seen this
                    if msg_id in self._seen_message_ids:
                        continue

                    self._seen_message_ids.add(msg_id)

                    message = IncomingMessage(
                        platform=Platform.MESSENGER,
                        sender_id=sender_id,
                        sender_name=sender_name,
                        content=content,
                        platform_message_id=msg_id,
                    )
                    messages.append(message)
                    log_message("inbound", sender_id, content)

                except Exception as e:
                    logger.debug(f"Error extracting message: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error extracting messages: {e}")

        return messages

    async def _get_conversation_name(self) -> Optional[str]:
        """Get the name from the conversation header."""
        try:
            name_selectors = [
                '[data-testid="conversation-header-title"]',
                'h2[dir="auto"]',
                '[aria-label*="Conversation with"]',
            ]

            for selector in name_selectors:
                elem = await self._page.query_selector(selector)
                if elem:
                    name = await elem.inner_text()
                    return name.strip()

        except Exception as e:
            logger.debug(f"Error getting conversation name: {e}")

        return None

    async def _get_conversation_id(self) -> Optional[str]:
        """Get the conversation ID from the URL."""
        try:
            url = self._page.url
            match = re.search(r'/t/(\d+)', url)
            if match:
                return match.group(1)
        except Exception:
            pass
        return None

    def _is_system_message(self, content: str) -> bool:
        """Check if a message is a system message (not from a user)."""
        system_patterns = [
            r'^You (sent|received|called|missed)',
            r'^(Audio|Video) call',
            r'^\d+:\d+\s*(AM|PM)?$',  # Timestamp
            r'^Seen',
            r'^Delivered',
            r'^(Today|Yesterday|\d+/\d+/\d+)',
            r'^You are now connected',
            r'sent a photo',
            r'sent a video',
            r'sent a link',
            r'sent an attachment',
        ]

        for pattern in system_patterns:
            if re.match(pattern, content, re.IGNORECASE):
                return True

        return False

    async def send_message(self, recipient_id: str, content: str) -> bool:
        """Send a message to a recipient."""
        try:
            # Navigate to conversation if needed
            if not await self._is_in_conversation(recipient_id):
                if not await self._open_conversation(recipient_id):
                    logger.error(f"Could not open conversation with {recipient_id}")
                    return False

            # Find message input
            input_selectors = [
                '[aria-label="Message"]',
                '[contenteditable="true"][role="textbox"]',
                'div[role="textbox"]',
                '[data-testid="message-input"]',
            ]

            input_elem = None
            for selector in input_selectors:
                try:
                    input_elem = await self._page.wait_for_selector(selector, timeout=5000)
                    if input_elem:
                        break
                except PlaywrightTimeout:
                    continue

            if not input_elem:
                logger.error("Could not find message input")
                return False

            # Click and type with human-like delays
            await input_elem.click()
            await asyncio.sleep(0.3)

            # Type the message
            for char in content:
                await self._page.keyboard.type(char)
                await asyncio.sleep(0.02 + 0.03 * (0.5 - abs(0.5 - len(content) / 500)))

            await asyncio.sleep(0.5)

            # Send with Enter or find send button
            send_selectors = [
                '[aria-label="Press enter to send"]',
                '[aria-label="Send"]',
                'button[type="submit"]',
            ]

            sent = False
            for selector in send_selectors:
                try:
                    send_btn = await self._page.query_selector(selector)
                    if send_btn:
                        await send_btn.click()
                        sent = True
                        break
                except Exception:
                    continue

            if not sent:
                # Fallback to Enter key
                await self._page.keyboard.press('Enter')

            await asyncio.sleep(0.5)
            log_message("outbound", recipient_id, content)
            logger.info(f"Sent message to {recipient_id}")
            return True

        except Exception as e:
            logger.error(f"Error sending message to {recipient_id}: {e}")
            return False

    async def _is_in_conversation(self, recipient_id: str) -> bool:
        """Check if we're currently in the target conversation."""
        current_id = await self._get_conversation_id()
        return current_id == recipient_id

    async def _open_conversation(self, recipient_id: str) -> bool:
        """Open a conversation by ID."""
        try:
            # Try direct URL navigation
            conv_url = f"{self.MESSENGER_URL}/t/{recipient_id}"
            await self._page.goto(conv_url, wait_until="networkidle")
            await asyncio.sleep(1)

            # Verify we're in the conversation
            if await self._is_in_conversation(recipient_id):
                return True

            # Try searching
            search_selectors = [
                '[aria-label="Search Messenger"]',
                '[placeholder*="Search"]',
                'input[type="search"]',
            ]

            for selector in search_selectors:
                try:
                    search = await self._page.query_selector(selector)
                    if search:
                        await search.click()
                        await search.fill(recipient_id)
                        await asyncio.sleep(1)

                        # Click first result
                        result = await self._page.query_selector('[data-testid="mwthreadlist-item"]')
                        if result:
                            await result.click()
                            await asyncio.sleep(1)
                            return True
                except Exception:
                    continue

            return False

        except Exception as e:
            logger.error(f"Error opening conversation: {e}")
            return False

    async def take_screenshot(self, name: str = "messenger") -> Path:
        """Take a debug screenshot."""
        if self._browser:
            return await self._browser.take_screenshot(name)
        return Path()
