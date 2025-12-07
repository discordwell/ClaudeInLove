#!/usr/bin/env python
"""Quick test script for Signal integration."""

import asyncio
import sys
sys.path.insert(0, '/home/user/ClaudeInLove')

from src.platforms.signal_client import SignalClient


async def test_signal():
    """Test Signal Desktop connection."""
    print("Testing Signal Desktop connection...")
    print("=" * 50)

    client = SignalClient()

    try:
        await client.connect()
        print("\n[OK] Connected to Signal Desktop!")

        # Try to get conversations
        print("\nGetting conversations...")
        conversations = await client.get_conversations()
        print(f"Found {len(conversations)} conversations")
        for conv in conversations[:5]:
            print(f"  - {conv}")

        # Check for new messages
        print("\nChecking for new messages...")
        messages = await client.get_new_messages()
        print(f"Found {len(messages)} new messages")
        for msg in messages:
            print(f"  - From {msg.sender_id}: {msg.content[:50]}...")

        await client.disconnect()
        print("\n[OK] Test completed successfully!")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        print("\nTo test Signal integration:")
        print("  1. Install Signal Desktop")
        print("  2. Launch with: signal-desktop --remote-debugging-port=9222")
        print("  3. Make sure you're logged in to Signal")
        print("  4. Run this script again")
        return False

    return True


if __name__ == "__main__":
    success = asyncio.run(test_signal())
    sys.exit(0 if success else 1)
