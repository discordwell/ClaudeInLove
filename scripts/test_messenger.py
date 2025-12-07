#!/usr/bin/env python
"""Quick test script for Facebook Messenger integration."""

import asyncio
import sys
sys.path.insert(0, '/home/user/ClaudeInLove')

from src.platforms.messenger_client import MessengerClient


async def test_messenger():
    """Test Messenger connection."""
    print("Testing Facebook Messenger integration...")
    print("=" * 50)
    print()
    print("NOTE: First run will require manual Facebook login.")
    print("      Subsequent runs will reuse the saved session.")
    print()

    # Run with visible browser for testing
    client = MessengerClient(headless=False)

    try:
        await client.connect()
        print("\n[OK] Connected to Messenger!")

        # Get conversations
        print("\nGetting conversations...")
        conversations = await client.get_conversations()
        print(f"Found {len(conversations)} conversations")
        for conv in conversations[:5]:
            print(f"  - {conv}")

        # Check for new messages
        print("\nChecking for new messages...")
        messages = await client.get_new_messages()
        print(f"Found {len(messages)} new messages")
        for msg in messages[:5]:
            preview = msg.content[:50] + "..." if len(msg.content) > 50 else msg.content
            print(f"  - From {msg.sender_name or msg.sender_id}: {preview}")

        print("\n[OK] Test completed successfully!")
        print("\nPress Enter to close browser...")
        input()

        await client.disconnect()
        return True

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()

        # Try to take screenshot for debugging
        try:
            screenshot = await client.take_screenshot("error")
            print(f"\nScreenshot saved: {screenshot}")
        except Exception:
            pass

        return False


if __name__ == "__main__":
    success = asyncio.run(test_messenger())
    sys.exit(0 if success else 1)
