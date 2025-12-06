"""
Stealth browser utilities for ClaudeInLove.
Adapted from twitter-signup project.
"""

import asyncio
import random
from pathlib import Path
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth
from fake_useragent import UserAgent

from ..core.config import get_config


# Desktop user agents (mobile gets different UIs)
DESKTOP_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
]


class StealthBrowser:
    """
    Playwright browser with anti-detection measures.
    """

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: Optional[Path] = None,
        slow_mo: int = 50,
    ):
        self.headless = headless
        self.user_data_dir = user_data_dir or get_config().browser_profile_dir
        self.slow_mo = slow_mo

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._stealth = Stealth()

    async def start(self) -> Page:
        """Launch browser and return the page."""
        config = get_config()

        self._playwright = await async_playwright().start()

        user_agent = random.choice(DESKTOP_USER_AGENTS)

        # Launch browser
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--window-size=1920,1080',
            ]
        )

        # Create context with anti-detection
        self._context = await self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=user_agent,
            locale='en-US',
            timezone_id='America/New_York',
            geolocation={'latitude': 40.7128, 'longitude': -74.0060},
            permissions=['geolocation'],
            color_scheme='light',
        )

        # Create page and apply stealth
        self._page = await self._context.new_page()
        await self._stealth.apply_stealth_async(self._page)

        # Additional anti-detection JavaScript
        await self._page.add_init_script("""
            // Hide webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Fake plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Fake languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Chrome runtime
            window.chrome = { runtime: {} };

            // Permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)

        return self._page

    async def close(self):
        """Close browser and cleanup."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self) -> Page:
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @property
    def page(self) -> Page:
        """Get the current page."""
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    async def take_screenshot(self, name: str) -> Path:
        """Take a screenshot for debugging."""
        config = get_config()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.screenshots_dir / f"{name}_{timestamp}.png"
        await self._page.screenshot(path=str(path), full_page=True)
        return path

    async def random_delay(self, min_ms: int = 500, max_ms: int = 2000):
        """Human-like random delay."""
        delay = random.randint(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    async def human_type(self, selector: str, text: str, click_first: bool = True):
        """Type like a human with random delays between keystrokes."""
        element = await self._page.wait_for_selector(selector, timeout=10000)

        if click_first:
            await element.click()
            await self.random_delay(200, 500)

        for char in text:
            await self._page.keyboard.type(char)
            await asyncio.sleep(random.uniform(0.05, 0.15))

    async def human_click(self, selector: str):
        """Click with human-like behavior."""
        element = await self._page.wait_for_selector(selector, timeout=10000)
        await self.random_delay(100, 300)
        await element.click()
        await self.random_delay(200, 500)


class PersistentBrowser(StealthBrowser):
    """
    Browser with persistent session (cookies, localStorage).
    Useful for maintaining ChatGPT login.
    """

    async def start(self) -> Page:
        """Launch browser with persistent context."""
        config = get_config()

        self._playwright = await async_playwright().start()

        user_agent = random.choice(DESKTOP_USER_AGENTS)

        # Ensure user data dir exists
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        # Launch with persistent context
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=self.headless,
            slow_mo=self.slow_mo,
            viewport={'width': 1920, 'height': 1080},
            user_agent=user_agent,
            locale='en-US',
            timezone_id='America/New_York',
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )

        # Get or create page
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        # Apply stealth
        await self._stealth.apply_stealth_async(self._page)

        # Anti-detection scripts
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
        """)

        return self._page

    async def close(self):
        """Close browser (context includes browser for persistent)."""
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
