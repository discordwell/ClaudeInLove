"""
Operator-facing statistics for ClaudeInLove.

Aggregates the data the database already records — engagements, message volume,
suspicion flags, time spent — into a single read-only snapshot so the operator
can see how much scammer time is being wasted and which conversations need
attention. Pure aggregation: no browser, nothing is ever sent.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from .database import Database
from .models import MessageDirection, ScammerStatus


@dataclass
class ConversationStat:
    """Per-scammer summary line for the overview."""
    scammer_id: str
    display_name: Optional[str]
    platform: str
    status: str
    message_count: int
    suspicion_flags: int
    first_contact: datetime
    last_contact: datetime

    @property
    def engagement(self) -> timedelta:
        """Span from first to last contact — a proxy for time wasted.

        Clamped to zero so a clock skew (last before first) can never make the
        operation-wide total go backwards.
        """
        return max(self.last_contact - self.first_contact, timedelta())


@dataclass
class Overview:
    """A whole-operation snapshot."""
    total_scammers: int
    by_status: dict
    total_messages: int
    inbound_messages: int
    outbound_messages: int
    pending_reviews: int
    total_engagement: timedelta
    conversations: List[ConversationStat] = field(default_factory=list)


async def gather_overview(db: Database) -> Overview:
    """Build an :class:`Overview` from the current database state."""
    scammers = await db.get_all_scammers()
    direction_counts = await db.count_messages_by_direction()
    pending = await db.count_unreviewed_flags()

    # Seed every status at zero so the breakdown is stable regardless of which
    # statuses happen to be present.
    by_status = {status.value: 0 for status in ScammerStatus}
    conversations: List[ConversationStat] = []
    total_engagement = timedelta()

    for s in scammers:
        by_status[s.status.value] = by_status.get(s.status.value, 0) + 1
        stat = ConversationStat(
            scammer_id=s.id,
            display_name=s.display_name,
            platform=s.platform.value,
            status=s.status.value,
            message_count=s.message_count,
            suspicion_flags=s.suspicion_flags,
            first_contact=s.first_contact,
            last_contact=s.last_contact,
        )
        conversations.append(stat)
        total_engagement += stat.engagement

    inbound = direction_counts.get(MessageDirection.INBOUND.value, 0)
    outbound = direction_counts.get(MessageDirection.OUTBOUND.value, 0)

    return Overview(
        total_scammers=len(scammers),
        by_status=by_status,
        # The messages table is the source of truth for volume, not the
        # denormalised per-scammer counter.
        total_messages=inbound + outbound,
        inbound_messages=inbound,
        outbound_messages=outbound,
        pending_reviews=pending,
        total_engagement=total_engagement,
        conversations=conversations,
    )


def human_duration(td: timedelta) -> str:
    """Render a duration compactly, e.g. ``3d 4h``, ``5h 2m``, ``<1m``."""
    total = int(td.total_seconds())
    if total < 60:
        return "<1m"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m"
