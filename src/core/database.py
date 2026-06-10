"""
SQLite database operations for ClaudeInLove.
"""

import aiosqlite
from pathlib import Path
from datetime import datetime
from typing import Optional, List
import json

from .models import (
    Scammer, Message, ContextSnapshot, Persona, SuspicionFlag,
    ScammerStatus, MessageDirection, Platform
)
from .config import get_config


SCHEMA = """
-- Scammer profiles
CREATE TABLE IF NOT EXISTS scammers (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    platform_id TEXT NOT NULL,
    display_name TEXT,
    first_contact TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_contact TIMESTAMP,
    message_count INTEGER DEFAULT 0,
    suspicion_flags INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    notes TEXT,
    UNIQUE(platform, platform_id)
);

-- Conversation messages
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scammer_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    platform_message_id TEXT,
    was_flagged BOOLEAN DEFAULT FALSE,
    flag_reason TEXT,
    FOREIGN KEY (scammer_id) REFERENCES scammers(id)
);

-- Context compression snapshots
CREATE TABLE IF NOT EXISTS context_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scammer_id TEXT NOT NULL,
    snapshot_type TEXT NOT NULL,
    content TEXT NOT NULL,
    message_range_start INTEGER,
    message_range_end INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scammer_id) REFERENCES scammers(id)
);

-- Persona document
CREATE TABLE IF NOT EXISTS persona (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    scraped_data TEXT,
    persona_document TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

-- Suspicion log
CREATE TABLE IF NOT EXISTS suspicion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scammer_id TEXT NOT NULL,
    message_id INTEGER,
    suspicion_score REAL,
    reason TEXT,
    human_reviewed BOOLEAN DEFAULT FALSE,
    reviewed_at TIMESTAMP,
    FOREIGN KEY (scammer_id) REFERENCES scammers(id),
    FOREIGN KEY (message_id) REFERENCES messages(id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_messages_scammer ON messages(scammer_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_scammers_status ON scammers(status);
"""


class Database:
    """Async SQLite database manager."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_config().db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Connect to database and initialize schema."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self):
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ==================== Scammer Operations ====================

    async def get_or_create_scammer(
        self,
        platform: Platform,
        platform_id: str,
        display_name: Optional[str] = None
    ) -> Scammer:
        """Get existing scammer or create new one."""
        async with self._conn.execute(
            "SELECT * FROM scammers WHERE platform = ? AND platform_id = ?",
            (platform.value, platform_id)
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            return Scammer(
                id=row["id"],
                platform=Platform(row["platform"]),
                platform_id=row["platform_id"],
                display_name=row["display_name"],
                first_contact=datetime.fromisoformat(row["first_contact"]),
                last_contact=datetime.fromisoformat(row["last_contact"]) if row["last_contact"] else datetime.now(),
                message_count=row["message_count"],
                suspicion_flags=row["suspicion_flags"],
                status=ScammerStatus(row["status"]),
                notes=row["notes"],
            )

        # Create new scammer
        scammer = Scammer(
            platform=platform,
            platform_id=platform_id,
            display_name=display_name,
        )

        await self._conn.execute(
            """INSERT INTO scammers
               (id, platform, platform_id, display_name, first_contact, last_contact, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (scammer.id, platform.value, platform_id, display_name,
             scammer.first_contact.isoformat(), scammer.last_contact.isoformat(),
             scammer.status.value)
        )
        await self._conn.commit()
        return scammer

    async def update_scammer(self, scammer: Scammer):
        """Update scammer record."""
        await self._conn.execute(
            """UPDATE scammers SET
               display_name = ?, last_contact = ?, message_count = ?,
               suspicion_flags = ?, status = ?, notes = ?
               WHERE id = ?""",
            (scammer.display_name, scammer.last_contact.isoformat(),
             scammer.message_count, scammer.suspicion_flags,
             scammer.status.value, scammer.notes, scammer.id)
        )
        await self._conn.commit()

    async def set_scammer_status(self, scammer_id: str, status: ScammerStatus):
        """Update only the status field for a scammer."""
        await self._conn.execute(
            "UPDATE scammers SET status = ? WHERE id = ?",
            (status.value, scammer_id)
        )
        await self._conn.commit()

    async def get_scammer_status(self, scammer_id: str) -> Optional[ScammerStatus]:
        """Get the current status for a scammer, or None if unknown."""
        async with self._conn.execute(
            "SELECT status FROM scammers WHERE id = ?",
            (scammer_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return ScammerStatus(row["status"]) if row else None

    async def get_paused_scammer_ids(self) -> List[str]:
        """Get IDs of all scammers currently paused for human review."""
        async with self._conn.execute(
            "SELECT id FROM scammers WHERE status = ?",
            (ScammerStatus.PAUSED.value,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [row["id"] for row in rows]

    async def get_active_scammers(self) -> List[Scammer]:
        """Get all active scammers."""
        async with self._conn.execute(
            "SELECT * FROM scammers WHERE status = 'active' ORDER BY last_contact DESC"
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            Scammer(
                id=row["id"],
                platform=Platform(row["platform"]),
                platform_id=row["platform_id"],
                display_name=row["display_name"],
                first_contact=datetime.fromisoformat(row["first_contact"]),
                last_contact=datetime.fromisoformat(row["last_contact"]) if row["last_contact"] else datetime.now(),
                message_count=row["message_count"],
                suspicion_flags=row["suspicion_flags"],
                status=ScammerStatus(row["status"]),
                notes=row["notes"],
            )
            for row in rows
        ]

    # ==================== Message Operations ====================

    async def add_message(
        self,
        scammer_id: str,
        direction: MessageDirection,
        content: str,
        platform_message_id: Optional[str] = None,
        was_flagged: bool = False,
        flag_reason: Optional[str] = None
    ) -> Message:
        """Add a message to the conversation."""
        now = datetime.now()

        cursor = await self._conn.execute(
            """INSERT INTO messages
               (scammer_id, direction, content, timestamp, platform_message_id, was_flagged, flag_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (scammer_id, direction.value, content, now.isoformat(),
             platform_message_id, was_flagged, flag_reason)
        )
        await self._conn.commit()

        # Update scammer last_contact and message_count
        await self._conn.execute(
            """UPDATE scammers SET
               last_contact = ?, message_count = message_count + 1
               WHERE id = ?""",
            (now.isoformat(), scammer_id)
        )
        await self._conn.commit()

        return Message(
            id=cursor.lastrowid,
            scammer_id=scammer_id,
            direction=direction,
            content=content,
            timestamp=now,
            platform_message_id=platform_message_id,
            was_flagged=was_flagged,
            flag_reason=flag_reason,
        )

    async def get_messages(
        self,
        scammer_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Message]:
        """Get messages for a scammer, newest first."""
        async with self._conn.execute(
            """SELECT * FROM messages
               WHERE scammer_id = ?
               ORDER BY timestamp DESC, id DESC
               LIMIT ? OFFSET ?""",
            (scammer_id, limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()

        messages = [
            Message(
                id=row["id"],
                scammer_id=row["scammer_id"],
                direction=MessageDirection(row["direction"]),
                content=row["content"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                platform_message_id=row["platform_message_id"],
                was_flagged=bool(row["was_flagged"]),
                flag_reason=row["flag_reason"],
            )
            for row in rows
        ]
        # Return in chronological order
        return list(reversed(messages))

    async def get_recent_messages(self, scammer_id: str, count: int = 20) -> List[Message]:
        """Get the most recent messages for context."""
        return await self.get_messages(scammer_id, limit=count)

    async def get_message_count(self, scammer_id: str) -> int:
        """Get total message count for a scammer."""
        async with self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE scammer_id = ?",
            (scammer_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    # ==================== Context Snapshot Operations ====================

    async def save_context_snapshot(
        self,
        scammer_id: str,
        snapshot_type: str,
        content: str,
        message_range_start: int,
        message_range_end: int
    ) -> ContextSnapshot:
        """Save a compressed context snapshot."""
        now = datetime.now()

        cursor = await self._conn.execute(
            """INSERT INTO context_snapshots
               (scammer_id, snapshot_type, content, message_range_start, message_range_end, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (scammer_id, snapshot_type, content, message_range_start, message_range_end, now.isoformat())
        )
        await self._conn.commit()

        return ContextSnapshot(
            id=cursor.lastrowid,
            scammer_id=scammer_id,
            snapshot_type=snapshot_type,
            content=content,
            message_range_start=message_range_start,
            message_range_end=message_range_end,
            created_at=now,
        )

    async def get_latest_snapshot(self, scammer_id: str) -> Optional[ContextSnapshot]:
        """Get the most recent context snapshot."""
        async with self._conn.execute(
            """SELECT * FROM context_snapshots
               WHERE scammer_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (scammer_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return ContextSnapshot(
            id=row["id"],
            scammer_id=row["scammer_id"],
            snapshot_type=row["snapshot_type"],
            content=row["content"],
            message_range_start=row["message_range_start"],
            message_range_end=row["message_range_end"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ==================== Persona Operations ====================

    async def save_persona(self, persona: Persona) -> Persona:
        """Save or update persona."""
        now = datetime.now()

        if persona.id:
            await self._conn.execute(
                """UPDATE persona SET
                   name = ?, scraped_data = ?, persona_document = ?, updated_at = ?
                   WHERE id = ?""",
                (persona.name, json.dumps(persona.scraped_data),
                 persona.persona_document, now.isoformat(), persona.id)
            )
        else:
            cursor = await self._conn.execute(
                """INSERT INTO persona (name, scraped_data, persona_document, created_at)
                   VALUES (?, ?, ?, ?)""",
                (persona.name, json.dumps(persona.scraped_data),
                 persona.persona_document, now.isoformat())
            )
            persona.id = cursor.lastrowid

        await self._conn.commit()
        return persona

    async def get_persona(self) -> Optional[Persona]:
        """Get the current persona (most recent)."""
        async with self._conn.execute(
            "SELECT * FROM persona ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return Persona(
            id=row["id"],
            name=row["name"],
            scraped_data=json.loads(row["scraped_data"]) if row["scraped_data"] else {},
            persona_document=row["persona_document"] or "",
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )

    # ==================== Suspicion Log Operations ====================

    async def log_suspicion(
        self,
        scammer_id: str,
        message_id: int,
        score: float,
        reason: str
    ) -> SuspicionFlag:
        """Log a suspicion flag."""
        cursor = await self._conn.execute(
            """INSERT INTO suspicion_log
               (scammer_id, message_id, suspicion_score, reason)
               VALUES (?, ?, ?, ?)""",
            (scammer_id, message_id, score, reason)
        )

        # Update scammer flag count
        await self._conn.execute(
            "UPDATE scammers SET suspicion_flags = suspicion_flags + 1 WHERE id = ?",
            (scammer_id,)
        )
        await self._conn.commit()

        return SuspicionFlag(
            id=cursor.lastrowid,
            scammer_id=scammer_id,
            message_id=message_id,
            suspicion_score=score,
            reason=reason,
        )

    async def get_unreviewed_flags(self) -> List[SuspicionFlag]:
        """Get all unreviewed suspicion flags."""
        async with self._conn.execute(
            """SELECT * FROM suspicion_log
               WHERE human_reviewed = FALSE
               ORDER BY suspicion_score DESC"""
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            SuspicionFlag(
                id=row["id"],
                scammer_id=row["scammer_id"],
                message_id=row["message_id"],
                suspicion_score=row["suspicion_score"],
                reason=row["reason"],
                human_reviewed=bool(row["human_reviewed"]),
            )
            for row in rows
        ]
