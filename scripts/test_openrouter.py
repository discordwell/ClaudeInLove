#!/usr/bin/env python
"""Test script for OpenRouter integration."""

import asyncio
import sys
sys.path.insert(0, '/home/user/ClaudeInLove')

from src.llm.openrouter_client import OpenRouterClient, FREE_MODELS


async def test_openrouter():
    """Test OpenRouter with different free models."""
    print("=" * 60)
    print("OpenRouter Free LLM Test")
    print("=" * 60)
    print()

    print("Available FREE models:")
    for alias, full_name in FREE_MODELS.items():
        print(f"  {alias:20} -> {full_name}")
    print()

    # Test with default model (DeepSeek R1)
    client = OpenRouterClient()

    try:
        await client.connect()
        print(f"Testing: {client.model}")
        print("-" * 40)

        # Simple test
        response = await client.send_message(
            "You are chatting with a romance scammer. They said 'Hello beautiful, "
            "I saw your profile and felt a connection.' Respond as a lonely person "
            "who is cautiously interested. Keep it to 1-2 sentences, be casual.",
            system_prompt="You are role-playing as a lonely person being targeted by "
            "romance scammers. Your goal is to waste their time. Be believable but "
            "never send money or real personal info. Use casual language with occasional typos."
        )

        print(f"Response: {response}")
        print("-" * 40)

        # Test conversation format
        print("\nTesting conversation format...")
        conv_response = await client.send_conversation([
            {"role": "system", "content": "You are a helpful assistant. Be brief."},
            {"role": "user", "content": "What's 2+2?"},
            {"role": "assistant", "content": "4"},
            {"role": "user", "content": "And if you add 3 more?"},
        ])
        print(f"Conversation response: {conv_response}")

        await client.disconnect()

        print()
        print("=" * 60)
        print("SUCCESS! OpenRouter is working.")
        print()
        print("To use OpenRouter, set in .env:")
        print("  LLM_PROVIDER=openrouter")
        print("  OPENROUTER_MODEL=deepseek-r1  # or qwen3, gemini-flash, llama-3.3")
        print("  OPENROUTER_API_KEY=your-key   # optional for free models")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

        print()
        print("Troubleshooting:")
        print("1. Check your internet connection")
        print("2. Try setting OPENROUTER_API_KEY (free to register)")
        print("3. Try a different model: OPENROUTER_MODEL=gemini-flash")
        print()
        print("Get free API key at: https://openrouter.ai/keys")

        return False


if __name__ == "__main__":
    success = asyncio.run(test_openrouter())
    sys.exit(0 if success else 1)
