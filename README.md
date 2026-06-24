# ClaudeInLove

Scam-baiter automation tool that wastes romance scammers' time with AI-powered responses.

## Features

- **Signal Desktop integration** - Monitor and respond to scammer messages via CDP
- **ChatGPT web automation** - Free LLM responses using your ChatGPT Plus subscription
- **Facebook persona scraping** - Build convincing alter ego from your own profile
- **Suspicion detection** - Check responses before sending to avoid AI detection
- **Hard-safety content guard** - Block any reply that would actually send money or leak PII
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

## Safety Guardrails

Two independent checks screen every drafted reply before it can be sent:

1. **Suspicion checker** — *"does this reply sound like an AI?"* Heuristic (plus
   optional LLM) scoring of robotic tells. A high score flags the reply for
   review; whether that also withholds it depends on `AUTO_PAUSE_ON_FLAG`.
2. **Content guard** — *"does this reply break the rules the tool exists to
   enforce?"* A deterministic backstop for the hard invariants: **never commit
   to sending money** (cash, wire, gift cards, crypto) and **never emit a real
   personal/financial identifier** (SSN, card/account/routing number, crypto
   wallet). These are a different failure mode from sounding robotic — a
   perfectly casual *"sure babe, I'll wire you the $500 on Western Union"*
   scores ~0 on the suspicion checker, yet is the single worst thing the bot
   could do against a counterparty actively trying to extract exactly that.

A content-guard violation **always** withholds the reply and pauses the
conversation for human review, regardless of the suspicion score **or** the
`AUTO_PAUSE_ON_FLAG` setting — the auto-pause opt-out governs ordinary
AI-suspicion flags, not hard-safety ones. The guard is precision-first: the
persona is *supposed* to talk about money in order to stall ("my account's
frozen", "I can't send anything till payday"), so deflections are left alone;
only an affirmative commitment to send trips it.

## Review Flagged Conversations

```bash
python scripts/review_flagged.py
```

Each pending review shows the scammer's message, the suspicion score/reason,
the conversation's current status, and the exact reply that was withheld, so you
can decide what to do. The choices are:

- **Resume** — clear the pause; the bot keeps engaging this conversation.
- **Pause** — keep it on hold (no auto-replies) until you resume it.
- **Archive** — retire the conversation for good (e.g. the scammer caught on or
  went silent); the bot never auto-replies again unless you later resume it.
- **Note** — attach a free-text note about this scammer (their claimed
  backstory, what they've asked for, anything to steer the persona). Notes
  accumulate and are injected into every future reply, so the alter ego stays
  consistent. Taking a note is *not* a decision: you're re-prompted for one of
  the actions above afterwards, and the flag stays in the queue until you decide.
- **Skip** — decide later; the flag stays in the queue.

Resume, Pause and Archive are all decisions, so they write the new status to the
database and mark that flag reviewed, so it drains from the queue and won't
reappear next run. The running main loop (and any later restart) honors the
status, because it only auto-replies to **active** conversations. Choosing
**Skip** leaves the flag pending for a later session.

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
the content-guard money/PII checks — both recall and precision so deflections
aren't blocked — context compression, database + schema migration, persona
building, phone normalization, message deduplication — including the durable
cross-restart check — the engagement-stats aggregation, and pause state) as
well as the main-loop orchestration end-to-end with the browser clients faked
(including that a money/PII reply is withheld even with auto-pause off). The
Playwright-driven clients themselves are exercised manually since they need a
live browser.

See [ARCHITECTURE.md](ARCHITECTURE.md) for a full module map and design notes.

## Architecture

```
Signal Desktop ─┐
                ├─► Main Loop ─► ChatGPT Web
Messenger (TBD)─┘       │
                        ├─► SQLite Storage
                        ├─► Suspicion Checker  (AI-detection risk)
                        ├─► Content Guard      (never send money / PII)
                        └─► Persona Context
```

## License

MIT
