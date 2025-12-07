# ClaudeInLove

Scam-baiter automation tool that wastes romance scammers' time with AI-powered responses.

## Features

- **Signal Desktop integration** - Monitor and respond to scammer messages via CDP
- **Facebook Messenger integration** - Automate messenger.com with persistent sessions
- **Free LLM via OpenRouter** - DeepSeek R1, Qwen3, Gemini Flash, Llama 3.3 - all free!
- **ChatGPT web automation** - Alternative using your ChatGPT Plus subscription
- **Facebook persona scraping** - Build convincing alter ego from your own profile
- **Suspicion detection** - Check responses before sending to avoid AI detection
- **Human review queue** - Flag and pause suspicious conversations (persistent across restarts)
- **Context compression** - Handle long conversations efficiently

## Setup

### 1. Install dependencies

```bash
pip install -e .
playwright install chromium
```

### 2. Start Signal Desktop with CDP (for Signal)

```bash
signal-desktop --remote-debugging-port=9222
```

Or use the provided script:
```bash
chmod +x scripts/start_signal.sh
./scripts/start_signal.sh
```

### 2b. Test Messenger (for Facebook Messenger)

```bash
python scripts/test_messenger.py
```

First run will open a browser for manual Facebook login. Session is saved for future runs.

### 3. Set up persona (optional but recommended)

```bash
python scripts/setup_persona.py
```

This will scrape your Facebook profile to build a convincing alter ego.

### 4. Run ClaudeInLove

```bash
python -m src.core.main_loop
```

Or using the entry point:
```bash
claudeinlove
```

## Configuration

Edit `.env` to customize:

```
# LLM Provider (openrouter = free, chatgpt = browser automation)
LLM_PROVIDER=openrouter
OPENROUTER_MODEL=deepseek-r1    # or: qwen3, gemini-flash, llama-3.3
OPENROUTER_API_KEY=             # optional - get free key at openrouter.ai/keys

# Platform
SIGNAL_DEBUG_PORT=9222

# Safety
SUSPICION_THRESHOLD=0.7
AUTO_PAUSE_ON_FLAG=true

# Human-like delays
MIN_RESPONSE_DELAY=30
MAX_RESPONSE_DELAY=180
```

### Free Models Available

| Model | Best For |
|-------|----------|
| `deepseek-r1` | Best reasoning, great for conversation (default) |
| `qwen3` | Good coder, fast responses |
| `gemini-flash` | Google's fast model |
| `llama-3.3` | Meta's latest, solid all-around |

Test OpenRouter setup:
```bash
python scripts/test_openrouter.py
```

## Usage

1. Launch Signal Desktop with CDP enabled (or use Messenger)
2. When scammers message you, ClaudeInLove will:
   - Store the message in SQLite
   - Build context with persona and conversation history
   - Generate response via OpenRouter (free) or ChatGPT
   - Check for AI-detection risk
   - Wait a human-like delay
   - Send the response

## Review Flagged Conversations

```bash
python scripts/review_flagged.py
```

## Architecture

```
Signal Desktop ──┐                    ┌─► OpenRouter API (free)
                 ├─► Main Loop ─────► │
Facebook Messenger┘       │           └─► ChatGPT Web (backup)
                          │
                          ├─► SQLite Storage
                          ├─► Suspicion Checker
                          └─► Persona Context
```

## License

MIT
