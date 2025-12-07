"""SQLite storage for beacon tokens and hits."""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import BeaconToken, BeaconHit, ScammerIntel


class BeaconDatabase:
    """Manages beacon token and hit storage."""

    def __init__(self, db_path: str = "data/beacons.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS beacon_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    token_type TEXT NOT NULL,
                    token_url TEXT NOT NULL,
                    bait_description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    deployed_at TIMESTAMP,
                    canary_token_id TEXT,
                    manage_url TEXT
                );

                CREATE TABLE IF NOT EXISTS beacon_hits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id INTEGER NOT NULL,
                    hit_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source_ip TEXT NOT NULL,
                    ip_geolocation TEXT,
                    user_agent TEXT,
                    referer TEXT,
                    hostname TEXT,
                    os_version TEXT,
                    username TEXT,
                    raw_headers TEXT,
                    FOREIGN KEY (token_id) REFERENCES beacon_tokens (id)
                );

                CREATE INDEX IF NOT EXISTS idx_hits_token ON beacon_hits(token_id);
                CREATE INDEX IF NOT EXISTS idx_hits_ip ON beacon_hits(source_ip);
                CREATE INDEX IF NOT EXISTS idx_tokens_conversation ON beacon_tokens(conversation_id);
            """
            )

    def create_token(self, token: BeaconToken) -> int:
        """Insert a new beacon token, return its ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO beacon_tokens
                (conversation_id, token_type, token_url, bait_description,
                 created_at, deployed_at, canary_token_id, manage_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    token.conversation_id,
                    token.token_type,
                    token.token_url,
                    token.bait_description,
                    token.created_at.isoformat(),
                    token.deployed_at.isoformat() if token.deployed_at else None,
                    token.canary_token_id,
                    token.manage_url,
                ),
            )
            return cursor.lastrowid

    def record_hit(self, hit: BeaconHit) -> int:
        """Record a beacon hit, return its ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO beacon_hits
                (token_id, hit_at, source_ip, ip_geolocation, user_agent,
                 referer, hostname, os_version, username, raw_headers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    hit.token_id,
                    hit.hit_at.isoformat(),
                    hit.source_ip,
                    hit.ip_geolocation,
                    hit.user_agent,
                    hit.referer,
                    hit.hostname,
                    hit.os_version,
                    hit.username,
                    hit.raw_headers,
                ),
            )
            return cursor.lastrowid

    def get_token_by_url(self, url: str) -> Optional[BeaconToken]:
        """Look up a token by its URL (for incoming callbacks)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM beacon_tokens WHERE token_url = ?", (url,)
            ).fetchone()
            if row:
                return self._row_to_token(row)
        return None

    def get_token_by_id(self, token_id: int) -> Optional[BeaconToken]:
        """Look up a token by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM beacon_tokens WHERE id = ?", (token_id,)
            ).fetchone()
            if row:
                return self._row_to_token(row)
        return None

    def get_hits_for_token(self, token_id: int) -> list[BeaconHit]:
        """Get all hits for a specific token."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM beacon_hits WHERE token_id = ? ORDER BY hit_at DESC",
                (token_id,),
            ).fetchall()
            return [self._row_to_hit(row) for row in rows]

    def get_intel_for_conversation(self, conversation_id: str) -> Optional[ScammerIntel]:
        """Aggregate all beacon intel for a conversation."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get all tokens for this conversation
            tokens = conn.execute(
                "SELECT id FROM beacon_tokens WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchall()

            if not tokens:
                return None

            token_ids = [t["id"] for t in tokens]
            placeholders = ",".join("?" * len(token_ids))

            # Get all hits for these tokens
            hits = conn.execute(
                f"""
                SELECT * FROM beacon_hits
                WHERE token_id IN ({placeholders})
                ORDER BY hit_at
            """,
                token_ids,
            ).fetchall()

            if not hits:
                return None

            # Aggregate
            ips = set()
            locations = set()
            hostnames = set()
            usernames = set()
            user_agents = set()

            for hit in hits:
                if hit["source_ip"]:
                    ips.add(hit["source_ip"])
                if hit["ip_geolocation"]:
                    locations.add(hit["ip_geolocation"])
                if hit["hostname"]:
                    hostnames.add(hit["hostname"])
                if hit["username"]:
                    usernames.add(hit["username"])
                if hit["user_agent"]:
                    user_agents.add(hit["user_agent"])

            return ScammerIntel(
                conversation_id=conversation_id,
                known_ips=list(ips),
                known_locations=list(locations),
                known_hostnames=list(hostnames),
                known_usernames=list(usernames),
                user_agents=list(user_agents),
                first_seen=datetime.fromisoformat(hits[0]["hit_at"]),
                last_seen=datetime.fromisoformat(hits[-1]["hit_at"]),
                total_hits=len(hits),
            )

    def get_recent_hits(self, limit: int = 50) -> list[tuple[BeaconHit, BeaconToken]]:
        """Get recent hits across all tokens for monitoring dashboard."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT h.*, t.conversation_id, t.token_type, t.bait_description
                FROM beacon_hits h
                JOIN beacon_tokens t ON h.token_id = t.id
                ORDER BY h.hit_at DESC
                LIMIT ?
            """,
                (limit,),
            ).fetchall()

            results = []
            for row in rows:
                hit = self._row_to_hit(row)
                token = self.get_token_by_id(row["token_id"])
                results.append((hit, token))
            return results

    def _row_to_token(self, row) -> BeaconToken:
        return BeaconToken(
            id=row["id"],
            conversation_id=row["conversation_id"],
            token_type=row["token_type"],
            token_url=row["token_url"],
            bait_description=row["bait_description"],
            created_at=datetime.fromisoformat(row["created_at"]),
            deployed_at=(
                datetime.fromisoformat(row["deployed_at"])
                if row["deployed_at"]
                else None
            ),
            canary_token_id=row["canary_token_id"],
            manage_url=row["manage_url"],
        )

    def _row_to_hit(self, row) -> BeaconHit:
        return BeaconHit(
            id=row["id"],
            token_id=row["token_id"],
            hit_at=datetime.fromisoformat(row["hit_at"]),
            source_ip=row["source_ip"],
            ip_geolocation=row["ip_geolocation"],
            user_agent=row["user_agent"],
            referer=row["referer"],
            hostname=row["hostname"],
            os_version=row["os_version"],
            username=row["username"],
            raw_headers=row["raw_headers"],
        )
