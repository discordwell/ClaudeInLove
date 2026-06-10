"""Tests for persona document construction and loading."""

import json

from src.persona.persona_builder import (
    build_persona_document,
    create_default_persona,
    create_persona_from_file,
    load_or_create_persona,
)


def test_build_persona_document_uses_scraped_fields():
    data = {
        "name": "Jamie Rivers",
        "location": "Lives in Austin, TX",
        "workplace": "Works at a coffee shop",
        "recent_posts": ["Loved the farmers market today!", "New plant friend 🌱"],
    }
    doc = build_persona_document(data)
    assert "Jamie Rivers" in doc
    assert "Austin" in doc
    assert "coffee shop" in doc
    assert "farmers market" in doc


def test_build_persona_document_falls_back_for_missing_fields():
    doc = build_persona_document({})
    assert "Your Name" in doc
    assert "Quiet life" in doc


def test_create_default_persona():
    persona = create_default_persona()
    assert persona.name == "Jordan Taylor"
    assert "Jordan Taylor" in persona.persona_document
    assert persona.scraped_data["location"]


async def test_create_persona_from_file(tmp_path, db):
    data = {"name": "Sam Doe", "location": "Lives in Reno", "recent_posts": []}
    json_path = tmp_path / "persona.json"
    json_path.write_text(json.dumps(data))

    persona = await create_persona_from_file(json_path=json_path, db=db)
    assert persona.name == "Sam Doe"
    assert persona.id  # persisted

    loaded = await db.get_persona()
    assert loaded.name == "Sam Doe"


async def test_load_or_create_persona_returns_existing(db):
    seed = create_default_persona()
    await db.save_persona(seed)

    loaded = await load_or_create_persona(db)
    assert loaded is not None
    assert loaded.name == "Jordan Taylor"


async def test_load_or_create_persona_returns_none_when_absent(db):
    # Empty DB and no persona file in the (temp) config dir.
    assert await load_or_create_persona(db) is None
