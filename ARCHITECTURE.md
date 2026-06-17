# Architecture

ClaudeInLove is a **reactive** scam-baiting assistant. It does not seek out
targets: it watches the operator's own Signal Desktop for inbound messages from
romance scammers (who initiate contact), drafts stalling replies through the
operator's own ChatGPT web session, screens each reply for "this might be an AI"
tells, and can pause any conversation for human review. The goal is to waste a
scammer's time, never to send money or real personal data.

## High-level flow

```
Signal Desktop ──(CDP poll)──► Main Loop ──► Context Manager ──► Prompt Builder
   (inbound)                       │                                   │
                                   │                                   ▼
                                   │                            ChatGPT (web)
                                   ▼                                   │
                            Suspicion Checker ◄─────── proposed reply ─┘
                                   │
                    score < threshold │ score ≥ threshold
                                   ▼                  ▼
                          human-like delay     Human Review Queue
                                   │            (pause + flag in DB)
                                   ▼
                         Signal Desktop (outbound)

                 SQLite stores scammers, messages, snapshots,
                 persona, and the suspicion log throughout.
```

## Module map

| Package | Module | Responsibility |
| --- | --- | --- |
| `core` | `main_loop.py` | Orchestration: poll → build context → generate → screen → delay → send. Owns startup/shutdown. |
| `core` | `config.py` | Env-driven `Config` (paths, thresholds, delays). Loaded once as a global singleton; `.env` is resolved relative to the project root. |
| `core` | `models.py` | Dataclasses + enums (`Scammer`, `Message`, `Persona`, `ContextSnapshot`, `SuspicionFlag`, `IncomingMessage`) with dict (de)serialization. |
| `core` | `database.py` | Async SQLite (`aiosqlite`). Schema + CRUD for all entities; pause state lives in `scammers.status`. |
| `llm` | `chatgpt_client.py` | Playwright automation of the ChatGPT web UI (uses the operator's logged-in session). |
| `llm` | `context_manager.py` | Three-tier context compression: recent window verbatim, LLM summary of older messages, snapshots persisted to the DB. Token-budget trimming. |
| `llm` | `prompt_builder.py` | Pure functions that assemble the system prompt (persona), conversation context, and the suspicion-check prompt. |
| `platforms` | `base.py` | `PlatformClient` ABC (connect / disconnect / get_new_messages / send_message / get_conversations). |
| `platforms` | `signal_client.py` | Signal Desktop via CDP. Polls unread conversations, extracts inbound messages, sends replies. Dedups by DOM id or a stable content fingerprint. |
| `safety` | `suspicion_checker.py` | Heuristic + optional LLM scoring of how "AI-like" a draft reply looks. No browser dependency (LLM client is injected). |
| `safety` | `human_review.py` | Pause/resume + review queue. Pause state is **DB-backed** so it survives restarts and is shared across processes. |
| `persona` | `facebook_scraper.py` | One-time scrape of the operator's *own* Facebook profile (Playwright). |
| `persona` | `persona_builder.py` | Turns scraped data into a persona document; provides a default persona for testing. |
| `utils` | `browser.py` | `StealthBrowser` / `PersistentBrowser` (Playwright with a persistent profile for staying logged in). |
| `utils` | `logging.py` | Rich console + rotating file logs; helpers for message/suspicion logging. |

## Data model (SQLite)

- **scammers** — one row per contact (`status` ∈ active/paused/flagged/archived; unique on `(platform, platform_id)`).
- **messages** — full conversation history (inbound/outbound, flag metadata).
- **context_snapshots** — compressed summaries of older messages.
- **persona** — the alter-ego document (most recent row wins).
- **suspicion_log** — every flagged reply, with score/reason, the withheld
  `proposed_response`, and a `human_reviewed` flag.

## Key design points

- **Reactive only.** Messages are processed because the scammer messaged the
  operator; nothing is sent unprompted.
- **Human review is authoritative and durable.** A flagged conversation is
  paused by writing `status = paused` to the database. `is_paused()` reads the
  DB, so the running loop, a restart, and the standalone `review_flagged.py`
  tool all agree. When a reply is withheld, the exact text the bot wanted to
  send is stored on the suspicion log (`proposed_response`) so the reviewer can
  judge it, not just its score.
- **AI probes always escalate to a human.** If an inbound message is testing
  for a bot ("are you a robot?"), the loop flags the exchange for review even
  when the drafted reply scores below the suspicion threshold — that is exactly
  the moment a person should decide what happens next.
- **Deduplication must be time-independent.** When a Signal message has no
  stable DOM id, `SignalClient._message_fingerprint(sender, content)` derives a
  deterministic id so the same message is never answered twice.
- **The safety layer is browser-free.** `suspicion_checker` takes its LLM client
  by injection and imports `ChatGPTClient` only under `TYPE_CHECKING`, so the
  screening logic can run (and be tested) without Playwright.

## Configuration

All runtime knobs are environment variables (see `.env.example`):
`SIGNAL_DEBUG_PORT`, `BROWSER_HEADLESS`, `SUSPICION_THRESHOLD`,
`AUTO_PAUSE_ON_FLAG`, `MIN_RESPONSE_DELAY`, `MAX_RESPONSE_DELAY`, `LOG_LEVEL`,
and the optional path overrides `DATA_DIR` / `LOG_DIR` / `BROWSER_USER_DATA_DIR`.

## Testing

`pytest` covers the deterministic layers — models, prompt building, suspicion
heuristics and LLM-result parsing, context compression, the database (including
schema migration of older DBs), persona building, phone normalization, message
fingerprinting, and DB-backed pause state. The main-loop orchestration
(`handle_incoming_message`) is covered end-to-end with the real database,
context manager, suspicion checker and review queue, faking only the two
browser-driven clients. The Playwright-driven clients (`signal_client`,
`chatgpt_client`, `facebook_scraper`) require a live browser and are exercised
manually. Run:

```bash
pip install -e ".[dev]"
pytest
```
