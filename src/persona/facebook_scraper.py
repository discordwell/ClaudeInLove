"""
Facebook profile scraper for building the alter ego persona.

Scrapes the user's own Facebook profile to extract:
- Name, location, workplace
- Interests, hobbies
- Relationship status
- Recent posts/activity
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from playwright.async_api import Page

from ..utils.browser import PersistentBrowser
from ..core.config import get_config
from ..utils.logging import logger


class FacebookScraper:
    """Scrapes user's own Facebook profile for persona building."""

    FACEBOOK_URL = "https://www.facebook.com"

    def __init__(self):
        config = get_config()
        self.browser = PersistentBrowser(
            headless=False,  # Need to see for login
            user_data_dir=config.browser_profile_dir / "facebook",
            slow_mo=50,
        )
        self._page: Optional[Page] = None

    async def connect(self):
        """Start browser and navigate to Facebook."""
        logger.info("Starting Facebook scraper...")

        self._page = await self.browser.start()
        await self._page.goto(self.FACEBOOK_URL, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Check if logged in
        if await self._needs_login():
            logger.warning("Facebook login required. Please log in manually.")
            logger.info("Waiting for login... (timeout: 5 minutes)")

            try:
                # Wait for main feed to appear (logged in state)
                await self._page.wait_for_selector(
                    '[role="feed"], [data-pagelet="Feed"]',
                    timeout=300000
                )
                logger.info("Login successful!")
            except Exception:
                raise RuntimeError("Login timeout")

        logger.info("Facebook scraper ready")

    async def _needs_login(self) -> bool:
        """Check if login is needed."""
        try:
            login_form = await self._page.query_selector(
                '#email, [data-testid="royal_email"]'
            )
            return login_form is not None
        except Exception:
            return False

    async def disconnect(self):
        """Close browser."""
        await self.browser.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def scrape_profile(self) -> Dict[str, Any]:
        """
        Scrape the user's own Facebook profile.

        Returns a dictionary with profile data.
        """
        data = {
            "scraped_at": datetime.now().isoformat(),
            "name": None,
            "location": None,
            "workplace": None,
            "education": None,
            "relationship_status": None,
            "about": None,
            "interests": [],
            "recent_posts": [],
        }

        try:
            # Navigate to profile
            await self._go_to_profile()

            # Extract basic info
            data["name"] = await self._extract_name()
            data["location"] = await self._extract_location()
            data["workplace"] = await self._extract_workplace()

            # Navigate to About page
            await self._go_to_about()
            about_data = await self._extract_about()
            data.update(about_data)

            # Get some recent posts
            await self._go_to_profile()
            data["recent_posts"] = await self._extract_recent_posts(limit=5)

            logger.info("Profile scrape complete")
            return data

        except Exception as e:
            logger.error(f"Error scraping profile: {e}")
            await self.browser.take_screenshot("facebook_error")
            return data

    async def _go_to_profile(self):
        """Navigate to user's own profile."""
        # Click profile link in navigation
        profile_link = await self._page.query_selector(
            'a[href*="/me"], [data-testid="profile-link"]'
        )

        if profile_link:
            await profile_link.click()
            await asyncio.sleep(2)
        else:
            # Try direct URL
            await self._page.goto(f"{self.FACEBOOK_URL}/me", wait_until="domcontentloaded")
            await asyncio.sleep(2)

    async def _go_to_about(self):
        """Navigate to About section of profile."""
        about_link = await self._page.query_selector(
            'a[href*="/about"], [data-testid="about-link"]'
        )

        if about_link:
            await about_link.click()
            await asyncio.sleep(2)

    async def _extract_name(self) -> Optional[str]:
        """Extract profile name."""
        try:
            name_elem = await self._page.query_selector(
                'h1, [data-testid="profile-name"]'
            )
            if name_elem:
                return await name_elem.inner_text()
        except Exception:
            pass
        return None

    async def _extract_location(self) -> Optional[str]:
        """Extract current city/location."""
        try:
            # Look for location in intro section
            intro = await self._page.query_selector_all(
                '[data-pagelet="ProfileTilesFeed_0"] span'
            )
            for elem in intro:
                text = await elem.inner_text()
                if "Lives in" in text or "From" in text:
                    return text
        except Exception:
            pass
        return None

    async def _extract_workplace(self) -> Optional[str]:
        """Extract workplace info."""
        try:
            intro = await self._page.query_selector_all(
                '[data-pagelet="ProfileTilesFeed_0"] span'
            )
            for elem in intro:
                text = await elem.inner_text()
                if "Works at" in text or "Worked at" in text:
                    return text
        except Exception:
            pass
        return None

    async def _extract_about(self) -> Dict[str, Any]:
        """Extract info from About page."""
        data = {
            "education": None,
            "relationship_status": None,
            "about": None,
            "interests": [],
        }

        try:
            # Get all text blocks from about page
            blocks = await self._page.query_selector_all(
                '[data-pagelet*="About"] span, [role="main"] span'
            )

            for block in blocks:
                text = await block.inner_text()

                # Relationship status
                if any(s in text.lower() for s in ["single", "married", "relationship", "engaged"]):
                    data["relationship_status"] = text

                # Education
                if any(s in text.lower() for s in ["studied", "went to", "university", "college", "school"]):
                    if not data["education"]:
                        data["education"] = text

        except Exception as e:
            logger.warning(f"Error extracting about: {e}")

        return data

    async def _extract_recent_posts(self, limit: int = 5) -> list:
        """Extract recent post content."""
        posts = []

        try:
            post_elements = await self._page.query_selector_all(
                '[data-ad-preview="message"], [data-testid="post-content"]'
            )

            for elem in post_elements[:limit]:
                text = await elem.inner_text()
                if text and len(text) > 10:
                    posts.append(text[:500])  # Truncate long posts

        except Exception:
            pass

        return posts

    async def save_scraped_data(self, data: Dict[str, Any], path: Path = None):
        """Save scraped data to JSON file."""
        config = get_config()
        path = path or config.persona_path

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved persona data to {path}")


async def scrape_facebook_profile(output_path: Path = None) -> Dict[str, Any]:
    """
    Convenience function to scrape Facebook profile.

    Returns scraped data and saves to file.
    """
    async with FacebookScraper() as scraper:
        data = await scraper.scrape_profile()
        await scraper.save_scraped_data(data, output_path)
        return data
