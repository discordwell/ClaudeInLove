"""Database models for beacon tracking."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class BeaconToken:
    """A deployed canary token linked to a scammer conversation."""

    id: Optional[int]
    conversation_id: str  # Links to scammer conversation
    token_type: str  # 'link', 'pdf', 'docx', 'exe'
    token_url: str  # The canarytoken callback URL or our tracking URL
    bait_description: str  # "Photo album", "Bank statement", etc.
    created_at: datetime
    deployed_at: Optional[datetime]  # When we sent it to scammer

    # Canarytokens.org specific
    canary_token_id: Optional[str]
    manage_url: Optional[str]  # URL to check hits on canarytokens.org


@dataclass
class BeaconHit:
    """A recorded hit on a beacon token."""

    id: Optional[int]
    token_id: int
    hit_at: datetime

    # Network info
    source_ip: str
    ip_geolocation: Optional[str]  # JSON blob from IP lookup

    # Request metadata
    user_agent: Optional[str]
    referer: Optional[str]

    # System info (if exe beacon)
    hostname: Optional[str]
    os_version: Optional[str]
    username: Optional[str]

    # Raw request data for analysis
    raw_headers: Optional[str]  # JSON


@dataclass
class ScammerIntel:
    """Aggregated intel on a scammer from multiple beacon hits."""

    conversation_id: str
    known_ips: list[str]
    known_locations: list[str]
    known_hostnames: list[str]
    known_usernames: list[str]
    user_agents: list[str]
    first_seen: datetime
    last_seen: datetime
    total_hits: int
