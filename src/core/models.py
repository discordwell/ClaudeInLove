"""
Data models for ClaudeInLove.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum
import uuid
import json


class ScammerStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    FLAGGED = "flagged"
    ARCHIVED = "archived"


class MessageDirection(Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Platform(Enum):
    SIGNAL = "signal"
    MESSENGER = "messenger"


@dataclass
class Scammer:
    """Represents a scammer we're engaging with."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    platform: Platform = Platform.SIGNAL
    platform_id: str = ""  # Phone number or FB ID
    display_name: Optional[str] = None
    first_contact: datetime = field(default_factory=datetime.now)
    last_contact: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    suspicion_flags: int = 0
    status: ScammerStatus = ScammerStatus.ACTIVE
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform.value,
            "platform_id": self.platform_id,
            "display_name": self.display_name,
            "first_contact": self.first_contact.isoformat(),
            "last_contact": self.last_contact.isoformat(),
            "message_count": self.message_count,
            "suspicion_flags": self.suspicion_flags,
            "status": self.status.value,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Scammer":
        return cls(
            id=data["id"],
            platform=Platform(data["platform"]),
            platform_id=data["platform_id"],
            display_name=data.get("display_name"),
            first_contact=datetime.fromisoformat(data["first_contact"]),
            last_contact=datetime.fromisoformat(data["last_contact"]),
            message_count=data.get("message_count", 0),
            suspicion_flags=data.get("suspicion_flags", 0),
            status=ScammerStatus(data.get("status", "active")),
            notes=data.get("notes"),
        )


@dataclass
class Message:
    """A single message in a conversation."""
    id: int = 0  # Auto-incremented by DB
    scammer_id: str = ""
    direction: MessageDirection = MessageDirection.INBOUND
    content: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    platform_message_id: Optional[str] = None
    was_flagged: bool = False
    flag_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scammer_id": self.scammer_id,
            "direction": self.direction.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "platform_message_id": self.platform_message_id,
            "was_flagged": self.was_flagged,
            "flag_reason": self.flag_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            id=data.get("id", 0),
            scammer_id=data["scammer_id"],
            direction=MessageDirection(data["direction"]),
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            platform_message_id=data.get("platform_message_id"),
            was_flagged=data.get("was_flagged", False),
            flag_reason=data.get("flag_reason"),
        )

    def format_for_context(self) -> str:
        """Format message for LLM context."""
        role = "Them" if self.direction == MessageDirection.INBOUND else "You"
        return f"{role}: {self.content}"


@dataclass
class ContextSnapshot:
    """Compressed context for a conversation."""
    id: int = 0
    scammer_id: str = ""
    snapshot_type: str = "summary"  # summary, full
    content: str = ""
    message_range_start: int = 0
    message_range_end: int = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Persona:
    """The alter ego persona based on Facebook profile."""
    id: int = 0
    name: str = ""
    scraped_data: dict = field(default_factory=dict)
    persona_document: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "scraped_data": json.dumps(self.scraped_data),
            "persona_document": self.persona_document,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class SuspicionFlag:
    """Record of a suspicion check."""
    id: int = 0
    scammer_id: str = ""
    message_id: int = 0
    suspicion_score: float = 0.0
    reason: str = ""
    proposed_response: Optional[str] = None  # The withheld reply, for the reviewer
    human_reviewed: bool = False
    reviewed_at: Optional[datetime] = None


@dataclass
class IncomingMessage:
    """Raw message from a platform before processing."""
    platform: Platform
    sender_id: str  # Phone number or platform ID
    sender_name: Optional[str]
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    platform_message_id: Optional[str] = None
