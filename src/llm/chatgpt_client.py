"""
ChatGPT web automation client.

Uses Playwright to automate chat.openai.com, avoiding API costs
by using the user's ChatGPT Plus subscription.
"""

import asyncio
import re
from typing import Optional
from datetime import datetime

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from ..utils.browser import PersistentBrowser
from ..core.config import get_config
from ..utils.logging import logger


class ChatGPTClient:
    """
    Automates ChatGPT web interface for free LLM access.

    Uses persistent browser session to maintain login.
    """

    CHATGPT_URL = "https://chat.openai.com"
    NEW_CHAT_URL = "https://chat.openai.com/?model=gpt-4"

    def __init__(self, browser_profile: str = None):
        config = get_config()
        self.browser = PersistentBrowser(
            headless=config.browser_headless,
            user_data_dir=browser_profile or config.browser_profile_dir / "chatgpt",
            slow_mo=30,
        )
        self._page: Optional[Page] = None
        self._connected = False

    async def connect(self):
        """Start browser and navigate to ChatGPT."""
        logger.info("Starting ChatGPT client...")

        self._page = await self.browser.start()

        # Navigate to ChatGPT
        await self._page.goto(self.CHATGPT_URL, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Check if we need to log in
        if await self._needs_login():
            logger.warning("ChatGPT login required. Please log in manually.")
            logger.info("Waiting for login... (timeout: 5 minutes)")

            # Wait for user to log in (look for chat interface)
            try:
                await self._page.wait_for_selector(
                    'textarea, #prompt-textarea',
                    timeout=300000  # 5 minutes
                )
                logger.info("Login successful!")
            except PlaywrightTimeout:
                raise RuntimeError("Login timeout. Please log in faster next time.")

        self._connected = True
        logger.info("ChatGPT client ready")

    async def _needs_login(self) -> bool:
        """Check if we need to log in."""
        try:
            # Look for login/signup buttons
            login_btn = await self._page.query_selector(
                'button:has-text("Log in"), button:has-text("Sign up"), '
                '[data-testid="login-button"]'
            )
            return login_btn is not None
        except Exception:
            return False

    async def disconnect(self):
        """Close browser."""
        await self.browser.close()
        self._connected = False
        logger.info("ChatGPT client disconnected")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def send_message(self, message: str, timeout: int = 120) -> str:
        """
        Send a message to ChatGPT and get the response.

        Args:
            message: The message to send
            timeout: Max seconds to wait for response

        Returns:
            The response text from ChatGPT
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            # Start a new chat for each conversation to avoid context pollution
            await self._start_new_chat()

            # Find the input textarea
            input_selector = 'textarea, #prompt-textarea, [data-testid="text-area"]'
            textarea = await self._page.wait_for_selector(input_selector, timeout=10000)

            if not textarea:
                raise RuntimeError("Could not find ChatGPT input field")

            # Clear any existing text
            await textarea.click()
            await self._page.keyboard.press('Control+A')
            await self._page.keyboard.press('Backspace')

            # Type the message with human-like delays
            await self._human_type(message)

            await asyncio.sleep(0.5)

            # Click send button or press Enter
            send_btn = await self._page.query_selector(
                'button[data-testid="send-button"], '
                'button[aria-label="Send message"], '
                'button:has(svg):right-of(textarea)'
            )

            if send_btn:
                await send_btn.click()
            else:
                await self._page.keyboard.press('Enter')

            # Wait for response
            response = await self._wait_for_response(timeout)
            return response

        except Exception as e:
            logger.error(f"Error sending message to ChatGPT: {e}")
            await self.browser.take_screenshot("chatgpt_error")
            raise

    async def _start_new_chat(self):
        """Start a new chat to avoid context from previous conversations."""
        try:
            # Look for new chat button
            new_chat_btn = await self._page.query_selector(
                'a[href="/"], button:has-text("New chat"), '
                '[data-testid="new-chat-button"]'
            )

            if new_chat_btn:
                await new_chat_btn.click()
                await asyncio.sleep(1)
            else:
                # Navigate directly to new chat
                await self._page.goto(self.NEW_CHAT_URL, wait_until="domcontentloaded")
                await asyncio.sleep(2)

        except Exception as e:
            logger.warning(f"Could not start new chat: {e}")

    async def _human_type(self, text: str):
        """Type text with human-like delays."""
        # For long prompts, paste instead of typing
        if len(text) > 500:
            # Use clipboard
            await self._page.evaluate(f'''
                navigator.clipboard.writeText({repr(text)})
            ''')
            await self._page.keyboard.press('Control+V')
        else:
            # Type character by character
            for char in text:
                await self._page.keyboard.type(char)
                await asyncio.sleep(0.02)  # Small delay

    async def _wait_for_response(self, timeout: int = 120) -> str:
        """Wait for ChatGPT to finish responding and return the text."""
        start = datetime.now()

        # Wait for response to start
        await asyncio.sleep(2)

        while True:
            # Check timeout
            elapsed = (datetime.now() - start).total_seconds()
            if elapsed > timeout:
                logger.warning("Response timeout, returning partial response")
                break

            # Check if still generating
            is_generating = await self._is_generating()

            if not is_generating:
                # Wait a bit more to ensure complete
                await asyncio.sleep(1)
                break

            await asyncio.sleep(1)

        # Extract the last response
        return await self._extract_last_response()

    async def _is_generating(self) -> bool:
        """Check if ChatGPT is still generating a response."""
        try:
            # Look for stop button (indicates generation in progress)
            stop_btn = await self._page.query_selector(
                'button:has-text("Stop generating"), '
                'button[aria-label="Stop generating"]'
            )
            return stop_btn is not None
        except Exception:
            return False

    async def _extract_last_response(self) -> str:
        """Extract the last assistant response from the page."""
        try:
            # Find all assistant messages
            messages = await self._page.query_selector_all(
                '[data-message-author-role="assistant"], '
                '.markdown.prose, '
                '.agent-turn .markdown'
            )

            if not messages:
                return ""

            # Get the last message
            last_message = messages[-1]
            text = await last_message.inner_text()

            # Clean up the text
            text = text.strip()

            return text

        except Exception as e:
            logger.error(f"Error extracting response: {e}")
            return ""

    async def check_session_valid(self) -> bool:
        """Check if the ChatGPT session is still valid."""
        try:
            # Look for indicators of logged-in state
            user_menu = await self._page.query_selector(
                '[data-testid="user-menu"], '
                'button[aria-label="Open settings"]'
            )
            return user_menu is not None
        except Exception:
            return False
