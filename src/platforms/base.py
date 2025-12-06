"""
Base class for messaging platform clients.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Optional
from datetime import datetime

from ..core.models import IncomingMessage, Platform


class PlatformClient(ABC):
    """Abstract base class for messaging platform clients."""

    platform: Platform

    @abstractmethod
    async def connect(self):
        """Connect to the platform."""
        pass

    @abstractmethod
    async def disconnect(self):
        """Disconnect from the platform."""
        pass

    @abstractmethod
    async def send_message(self, recipient_id: str, content: str) -> bool:
        """
        Send a message to a recipient.
        Returns True if successful.
        """
        pass

    @abstractmethod
    async def get_new_messages(self) -> List[IncomingMessage]:
        """
        Get new unread messages.
        Returns list of new messages since last check.
        """
        pass

    @abstractmethod
    async def get_conversations(self) -> List[str]:
        """
        Get list of active conversation IDs.
        """
        pass

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
