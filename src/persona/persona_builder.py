"""
Build the alter ego persona document from scraped Facebook data.
"""

import json
from pathlib import Path
from typing import Optional

from ..core.models import Persona
from ..core.database import Database
from ..core.config import get_config
from ..utils.logging import logger


# Template for persona document
PERSONA_TEMPLATE = """Name: {name}
Location: {location}
Work: {workplace}
Education: {education}
Relationship Status: {relationship_status}

Background:
{about}

Personality traits for the scam-baiting persona:
- Lonely but hopeful about finding love online
- Trusting, perhaps too trusting, but learning to be cautious
- Has some money saved but is careful with finances
- Values emotional connection over material things
- Occasionally mentions being busy with work/family
- Has been hurt before but willing to try again

Important boundaries (never reveal real info about):
- Actual home address (use vague neighborhood)
- Real family member names
- Bank account details
- Social security or ID numbers

Hooks to keep scammers engaged:
- Mention upcoming paycheck/bonus (but delays when asked for money)
- Talk about wanting to meet in person eventually
- Share "dreams" about future together
- Ask lots of questions about their life

Recent life context from posts:
{recent_context}
"""


def build_persona_document(scraped_data: dict) -> str:
    """
    Build the persona document from scraped Facebook data.

    Args:
        scraped_data: Dictionary from Facebook scraper

    Returns:
        Formatted persona document string
    """
    # Extract recent post summaries
    recent = scraped_data.get("recent_posts", [])
    recent_context = "\n".join(f"- {post[:100]}..." for post in recent[:3]) if recent else "- Quiet life, doesn't post much"

    return PERSONA_TEMPLATE.format(
        name=scraped_data.get("name") or "Your Name",
        location=scraped_data.get("location") or "somewhere in the US",
        workplace=scraped_data.get("workplace") or "works from home",
        education=scraped_data.get("education") or "some college",
        relationship_status=scraped_data.get("relationship_status") or "Single",
        about=scraped_data.get("about") or "A regular person looking for connection.",
        recent_context=recent_context,
    )


async def create_persona_from_file(json_path: Path = None, db: Database = None) -> Persona:
    """
    Load scraped data from file and create/save persona.

    Args:
        json_path: Path to scraped JSON data
        db: Database instance (optional, for saving)

    Returns:
        The created Persona object
    """
    config = get_config()
    json_path = json_path or config.persona_path

    if not json_path.exists():
        raise FileNotFoundError(f"No scraped data found at {json_path}. Run the Facebook scraper first.")

    with open(json_path) as f:
        scraped_data = json.load(f)

    # Build persona document
    document = build_persona_document(scraped_data)

    persona = Persona(
        name=scraped_data.get("name") or "Unknown",
        scraped_data=scraped_data,
        persona_document=document,
    )

    # Save to database if provided
    if db:
        persona = await db.save_persona(persona)
        logger.info(f"Saved persona '{persona.name}' to database")

    return persona


async def load_or_create_persona(db: Database) -> Optional[Persona]:
    """
    Load existing persona from database, or create from file if available.

    Returns None if no persona data exists.
    """
    # Try database first
    persona = await db.get_persona()
    if persona:
        return persona

    # Try creating from file
    config = get_config()
    if config.persona_path.exists():
        return await create_persona_from_file(db=db)

    return None


def create_default_persona() -> Persona:
    """
    Create a default persona if no Facebook data is available.

    This is a fallback for testing without scraping.
    """
    default_data = {
        "name": "Jordan Taylor",
        "location": "Lives in Chicago, Illinois",
        "workplace": "Works at a local retail store",
        "education": "Studied Business at community college",
        "relationship_status": "Single",
        "about": "Just a regular person trying to find happiness. Love hiking, cooking, and quiet nights at home.",
        "recent_posts": [
            "Beautiful sunset today! Feeling grateful.",
            "Finally got that promotion at work!",
            "Missing my family back home...",
        ],
    }

    document = build_persona_document(default_data)

    return Persona(
        name=default_data["name"],
        scraped_data=default_data,
        persona_document=document,
    )
