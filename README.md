# ClaudeInLove

Scam-baiter automation tool that wastes romance scammers' time with AI-powered responses.

## Features

- **Signal Desktop integration** - Monitor and respond to scammer messages via CDP
- **ChatGPT web automation** - Free LLM responses using your ChatGPT Plus subscription
- **Facebook persona scraping** - Build convincing alter ego from your own profile
- **Suspicion detection** - Check responses before sending to avoid AI detection
- **Human review queue** - Flag and pause suspicious conversations
- **Context compression** - Handle long conversations efficiently

## Setup

### 1. Install dependencies

```bash
pip install -e .
playwright install chromium
```

### 2. Start Signal Desktop with CDP

```bash
signal-desktop --remote-debugging-port=9222
```

Or use the provided script:
```bash
chmod +x scripts/start_signal.sh
./scripts/start_signal.sh
```

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
SIGNAL_DEBUG_PORT=9222
SUSPICION_THRESHOLD=0.7
AUTO_PAUSE_ON_FLAG=true
MIN_RESPONSE_DELAY=30
MAX_RESPONSE_DELAY=180
```

## Usage

1. Launch Signal Desktop with CDP enabled
2. Launch ChatGPT in your browser (will prompt for login on first run)
3. When scammers message you, ClaudeInLove will:
   - Store the message in SQLite
   - Build context with persona and conversation history
   - Generate response via ChatGPT
   - Check for AI-detection risk
   - Wait a human-like delay
   - Send the response

## Review Flagged Conversations

```bash
python scripts/review_flagged.py
```

Each pending review shows the scammer's message, the suspicion score/reason,
and the exact reply that was withheld, so you can decide whether to resume.
Pausing or resuming here is written to the database, so the running main loop
(and any later restart) honors your decision. Resuming or pausing also marks
that flag as reviewed, so it drains from the queue and won't reappear next run;
choosing **Skip** leaves it pending for a later session.

## Engagement Stats

```bash
python scripts/stats.py
```

Prints a read-only overview of every conversation: how many scammers are
engaged (broken down by active/paused/flagged/archived), total messages
exchanged (inbound vs. outbound), the cumulative "time wasted" across all
conversations, and how many replies are still pending review — plus a
per-scammer table of message counts, suspicion flags, and engagement duration.
It never opens a browser or sends anything, so it is safe to run while the main
loop is live.

## Development

Install the dev extras and run the test suite:

```bash
pip install -e ".[dev]"
pytest
```

The tests cover the deterministic logic (models, prompts, suspicion scoring,
context compression, database + schema migration, persona building, phone
normalization, message deduplication — including the durable cross-restart
check — the engagement-stats aggregation, and pause state) as well as the
main-loop orchestration end-to-end with the browser clients faked. The
Playwright-driven clients themselves are exercised manually since they need a
live browser.

See [ARCHITECTURE.md](ARCHITECTURE.md) for a full module map and design notes.

## Architecture

```
Signal Desktop ─┐
                ├─► Main Loop ─► ChatGPT Web
Messenger (TBD)─┘       │
                        ├─► SQLite Storage
                        ├─► Suspicion Checker
                        └─► Persona Context
```

## License

MIT
