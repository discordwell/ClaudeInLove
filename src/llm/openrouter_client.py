"""
OpenRouter API client for free LLM access.

OpenRouter provides access to many models including free ones:
- deepseek/deepseek-r1:free - Best reasoning
- qwen/qwen3-coder:free - Good for conversation
- google/gemini-2.0-flash-exp:free - Fast responses
- meta-llama/llama-3.3-70b-instruct:free - Solid general purpose

Set OPENROUTER_API_KEY in .env or use without key for limited access.
"""

import httpx
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from ..core.config import get_config
from ..utils.logging import logger


# Free models available on OpenRouter (as of 2025)
FREE_MODELS = {
    "deepseek-r1": "deepseek/deepseek-r1:free",
    "deepseek-r1-llama": "deepseek/deepseek-r1-distill-llama-70b:free",
    "qwen3": "qwen/qwen3-coder:free",
    "gemini-flash": "google/gemini-2.0-flash-exp:free",
    "llama-3.3": "meta-llama/llama-3.3-70b-instruct:free",
}

DEFAULT_MODEL = "deepseek-r1"


@dataclass
class OpenRouterConfig:
    """OpenRouter-specific configuration."""
    api_key: Optional[str]
    model: str
    base_url: str = "https://openrouter.ai/api/v1"
    site_url: str = "https://github.com/claudeinlove"  # For OpenRouter rankings
    site_name: str = "ClaudeInLove"
    max_tokens: int = 1024
    temperature: float = 0.8


class OpenRouterClient:
    """
    OpenRouter API client for accessing free LLMs.

    Much simpler than browser automation - just HTTP requests.
    Supports multiple free models that can be swapped easily.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = None,
    ):
        """
        Initialize OpenRouter client.

        Args:
            api_key: OpenRouter API key (optional for some free models)
            model: Model name or alias (see FREE_MODELS)
        """
        import os

        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")

        # Resolve model alias to full name
        model_input = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self.model = FREE_MODELS.get(model_input, model_input)

        self.base_url = "https://openrouter.ai/api/v1"
        self.max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", "1024"))
        self.temperature = float(os.getenv("OPENROUTER_TEMPERATURE", "0.8"))

        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False

    async def connect(self):
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            headers=self._build_headers(),
        )
        self._connected = True
        logger.info(f"OpenRouter client ready (model: {self.model})")

    async def disconnect(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
        self._connected = False
        logger.info("OpenRouter client disconnected")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers."""
        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/claudeinlove",
            "X-Title": "ClaudeInLove",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    async def send_message(
        self,
        message: str,
        timeout: int = 120,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Send a message and get a response.

        Compatible with ChatGPTClient interface.

        Args:
            message: The user message to send
            timeout: Request timeout in seconds
            system_prompt: Optional system prompt (for scam-baiting persona)

        Returns:
            The model's response text
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")

        messages = []

        # Add system prompt if provided
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })

        # Add user message
        messages.append({
            "role": "user",
            "content": message
        })

        return await self._chat_completion(messages, timeout)

    async def send_conversation(
        self,
        messages: List[Dict[str, str]],
        timeout: int = 120,
    ) -> str:
        """
        Send a full conversation and get a response.

        Args:
            messages: List of {"role": "user/assistant/system", "content": "..."}
            timeout: Request timeout in seconds

        Returns:
            The model's response text
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")

        return await self._chat_completion(messages, timeout)

    async def _chat_completion(
        self,
        messages: List[Dict[str, str]],
        timeout: int = 120,
    ) -> str:
        """Make a chat completion request."""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        try:
            response = await self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=timeout,
            )

            if response.status_code == 429:
                logger.warning("Rate limited by OpenRouter, waiting...")
                import asyncio
                await asyncio.sleep(5)
                # Retry once
                response = await self._client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    timeout=timeout,
                )

            response.raise_for_status()
            data = response.json()

            # Extract response text
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0]["message"]["content"]

                # Log token usage if available
                if "usage" in data:
                    usage = data["usage"]
                    logger.debug(
                        f"Tokens: {usage.get('prompt_tokens', '?')} in, "
                        f"{usage.get('completion_tokens', '?')} out"
                    )

                return content.strip()
            else:
                logger.error(f"Unexpected response format: {data}")
                return ""

        except httpx.HTTPStatusError as e:
            logger.error(f"OpenRouter API error: {e.response.status_code}")
            logger.error(f"Response: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error calling OpenRouter: {e}")
            raise

    async def check_session_valid(self) -> bool:
        """Check if the client is ready (always true if connected)."""
        return self._connected

    def set_model(self, model: str):
        """
        Switch to a different model.

        Args:
            model: Model name or alias from FREE_MODELS
        """
        self.model = FREE_MODELS.get(model, model)
        logger.info(f"Switched to model: {self.model}")

    @staticmethod
    def list_free_models() -> Dict[str, str]:
        """Return available free model aliases."""
        return FREE_MODELS.copy()


async def test_openrouter():
    """Quick test of OpenRouter connection."""
    client = OpenRouterClient()

    try:
        await client.connect()

        print(f"Testing model: {client.model}")
        print("-" * 50)

        response = await client.send_message(
            "Say 'Hello! OpenRouter is working!' and nothing else.",
            system_prompt="You are a helpful assistant. Be very brief."
        )

        print(f"Response: {response}")
        print("-" * 50)
        print("✓ OpenRouter is working!")

        await client.disconnect()
        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        return False


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_openrouter())
