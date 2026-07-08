# Architecture

ClaudeInLove is a **reactive** scam-baiting assistant. It does not seek out
targets: it watches the operator's own Signal Desktop for inbound messages from
romance scammers (who initiate contact), drafts stalling replies through the
operator's own ChatGPT web session, screens each reply for "this might be an AI"
tells **and for hard-safety violations** (a reply that would actually send money
or leak PII), and can pause any conversation for human review. The goal is to
waste a scammer's time, never to send money or real personal data.

## High-level flow

```
Signal Desktop ──(CDP poll)──► Main Loop ──► Context Manager ──► Prompt Builder
   (inbound)                       │                                   │
                                   │                                   ▼
                                   │                            ChatGPT (web)
                                   ▼                                   │
                  Suspicion Checker + Content Guard ◄─ proposed reply ─┘
                                   │
              safe & score<thresh  │  AI tells (score≥thresh) OR safety violation
                                   ▼                  ▼
                          human-like delay     Human Review Queue
                                   │            (pause + flag in DB)
                                   ▼            (a safety violation always
                         Signal Desktop          withholds + pauses, even
                            (outbound)            when auto-pause is off)

                 SQLite stores scammers, messages, snapshots,
                 persona, and the suspicion log throughout.
```

## Module map

| Package | Module | Responsibility |
| --- | --- | --- |
| `core` | `main_loop.py` | Orchestration: poll → build context → generate → screen → delay → send. Owns startup/shutdown. |
| `core` | `config.py` | Env-driven `Config` (paths, thresholds, delays). Loaded once as a global singleton; `.env` is resolved relative to the project root. |
| `core` | `models.py` | Dataclasses + enums (`Scammer`, `Message`, `Persona`, `ContextSnapshot`, `SuspicionFlag`, `IncomingMessage`) with dict (de)serialization. |
| `core` | `database.py` | Async SQLite (`aiosqlite`). Schema + CRUD for all entities; pause state lives in `scammers.status`. Durable dedup via `has_inbound_message`. |
| `core` | `stats.py` | Read-only aggregation of engagements, message volume, flags, and time-wasted into an `Overview` for the operator. No browser; nothing is sent. |
| `llm` | `chatgpt_client.py` | Playwright automation of the ChatGPT web UI (uses the operator's logged-in session). |
| `llm` | `context_manager.py` | Three-tier context compression: recent window verbatim, LLM summary of older messages, snapshots persisted to the DB. Token-budget trimming. |
| `llm` | `prompt_builder.py` | Pure functions that assemble the system prompt (persona), conversation context, and the suspicion-check prompt. |
| `platforms` | `base.py` | `PlatformClient` ABC (connect / disconnect / get_new_messages / send_message / get_conversations). |
| `platforms` | `signal_client.py` | Signal Desktop via CDP. Polls unread conversations, extracts inbound messages, sends replies. Dedups by DOM id or a stable content fingerprint. |
| `safety` | `suspicion_checker.py` | Heuristic + optional LLM scoring of how "AI-like" a draft reply looks. No browser dependency (LLM client is injected). |
| `safety` | `content_guard.py` | Deterministic backstop enforcing the hard invariants on every outgoing reply: never commit to **sending money** (cash/wire/gift cards/crypto), never emit **PII** (SSN, card/account/routing number, crypto wallet). Pure regex, no deps. Precision-first so money *deflections* aren't blocked. |
| `safety` | `human_review.py` | Pause/resume/archive + review queue + operator notes. Pause state is **DB-backed** so it survives restarts and is shared across processes. |
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
  `proposed_response`, and a `human_reviewed`/`reviewed_at` pair that the review
  tool sets once a human acts on the flag (so the queue actually drains).

## Key design points

- **Reactive only.** Messages are processed because the scammer messaged the
  operator; nothing is sent unprompted.
- **The loop only auto-replies to `active` conversations.** `scammers.status`
  is the conversation's lifecycle state: `active` (engage normally), `paused`
  (a temporary hold for human review), `archived` (retired — the scammer caught
  on, went silent, or the operator is done), and `flagged` (reserved). The main
  loop gates on `status == active`, **not** merely "not paused", so *every*
  non-active state suppresses the automatic reply. Gating only on `is_paused`
  would silently keep answering an archived (or otherwise non-active)
  conversation. Resuming sets the status back to `active`.
- **Human review is authoritative and durable.** A flagged conversation is
  paused by writing `status = paused` to the database. `is_paused()` reads the
  DB, so the running loop, a restart, and the standalone `review_flagged.py`
  tool all agree. The review tool can **Resume** (→ active), **Pause** (stay
  paused), or **Archive** (→ archived) a flagged conversation — each is a
  decision, so each also marks the flag reviewed (see below). When a reply is withheld, the exact text the bot wanted to
  send is stored on the suspicion log (`proposed_response`) so the reviewer can
  judge it, not just its score. The queue pairs each flag with the exact
  message it was raised against (`SuspicionFlag.message_id` →
  `Database.get_message_by_id`), never merely the latest message — otherwise a
  second flag, or an auto-sent reply stored after the flag, would mislabel what
  is under review (even showing our own outbound reply as "their message").
  Acting on a flag (resume or pause) calls
  `mark_flag_reviewed`, which sets `human_reviewed`/`reviewed_at`; without it the
  unreviewed-flags query would re-surface every flag forever and the queue could
  never be drained. Skipping leaves the flag pending.
- **Operator notes steer the persona.** `build_full_prompt` injects
  `scammers.notes` into every reply as `[Notes about this scammer: ...]`, but
  nothing used to write that column, so the feature was dormant. The review tool
  now offers a **Note** action (`HumanReviewQueue.add_note` →
  `Database.set_scammer_notes`) that appends a free-text note (newline-separated,
  so observations accumulate across sessions) to the conversation. A note is
  *not* a review decision: it leaves `scammers.status` and the flag's reviewed
  state untouched and re-prompts for a real action, so an annotated flag still
  has to be resumed/paused/archived/skipped. The notes then flow into the next
  generated reply, keeping the alter ego consistent with what the operator has
  learned (claimed backstory, money asks, etc.).
- **AI probes always escalate to a human.** If an inbound message is testing
  for a bot ("are you a robot?"), the loop flags the exchange for review even
  when the drafted reply scores below the suspicion threshold — that is exactly
  the moment a person should decide what happens next.
- **Hard-safety violations are blocked in code, not just in the prompt.** The
  invariant "never send money or real personal data" lived only in the system
  prompt and the persona template — prose the LLM may ignore under pressure or
  be steered past by an injection in the scammer's own message. `content_guard`
  is the deterministic enforcement: it screens every drafted reply for an
  affirmative commitment to send funds (money/cash/$/gift cards/crypto, payment
  apps, buying gift cards) and for personal/financial identifiers (SSN,
  card/account-length numbers, labelled bank numbers, crypto wallets). This is a
  *distinct* failure mode from sounding robotic: a casual "sure, I'll wire you
  the $500" scores ~0 on `suspicion_checker` yet is the worst possible outcome,
  so the guard runs independently of the suspicion score. A violation **always**
  forces review *and* withholds the reply, overriding `auto_pause_on_flag`
  (`HumanReviewQueue.flag_for_review(force_pause=...)`); the loop also raises the
  logged score to `1.0` so the flag sorts to the top of the review queue. The
  guard is **precision-first**: the persona is meant to discuss money to stall
  ("my account's frozen", "I can't send anything"), so money checks run clause
  by clause and require the sending verb and its money object to sit within a
  few words (an unrelated co-occurrence like "send you a hug instead, money's
  too tight" does not trip it). Negation is **scoped to the verb it governs**,
  not the whole clause: the guard blanks out only the span where a negation
  *directly governs a sending verb* ("I can't **send**", "won't **wire**", "not
  going to **buy**") — that is the refusal — and screens whatever commitment
  remains. A negation aimed at some *other* verb therefore can no longer shield a
  real commitment riding alongside it: "**don't worry** babe I'll **wire** the
  500" and "I **can't wait** to **send** you the money" are now caught (an
  earlier clause-level skip swallowed the whole sentence and let these through at
  suspicion score ~0 — the worst-case miss). The `_NEG_BREAKER` set (future
  lead-ins like "I'll", eager idioms like "can't wait"/"won't hesitate") marks
  where a negation stops governing, so deflections ("I can't send", "no way I'm
  sending") still pass while capitulations do not. PII/identifier checks run on
  the whole reply, since those strings are never legitimate to emit: an SSN is
  matched in any common shape (3-2-4 dashed/spaced/dotted, or a bare nine digits
  when explicitly labelled "ssn"/"social"). The 13-digit floor on the
  card/account heuristic sits above any phone number, so "call me at
  +1 555 123 4567" is left alone.
- **Deduplication must be time-independent _and_ durable.** When a Signal
  message has no stable DOM id, `SignalClient._message_fingerprint(sender,
  content)` derives a deterministic id so the same message is never answered
  twice within a session. The client's in-memory seen-set is lost on restart,
  though, so the main loop also consults the `messages` table
  (`Database.has_inbound_message`) before acting: a real platform id we have
  already stored is skipped, so a restart can't make the bot re-answer (and
  double-text) a scammer. This durable check is scoped to real platform ids —
  content fingerprints (`IncomingMessage.synthetic_id`) collide for identical
  text, so they would otherwise suppress a repeated "good morning" forever and
  are left to the per-session seen-set.
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
heuristics and LLM-result parsing, the content guard (recall: money commitments
and PII are blocked — including "warm capitulations" where a refusal and a
commitment share one comma-less breath, and an SSN in any common format;
**precision**: ordinary chatter, money *deflections* and unlabelled phone/order
numbers are not, plus a discriminator pinning that negation scope — not mere
presence — decides safe vs. blocked, and an adversarial corpus assertion that
the dangerous reply is invisible to the suspicion checker so the block is
attributable to the guard), context
compression, the database (including
schema migration of older DBs, durable dedup, and the stats aggregates),
persona building, phone normalization, message fingerprinting, the stats
overview, DB-backed pause state, the conversation lifecycle (pause / resume /
archive, and that the review queue reports each conversation's real status and
surfaces each flag's own message, not just the most recent one), and operator
notes (round-trip persistence, that `add_note` appends rather than overwrites
and ignores blanks, that the pending-review rows carry the notes, and that the
interactive **Note** action saves a note without marking the flag reviewed and
re-prompts for a decision). The main-loop
orchestration (`handle_incoming_message`) is covered end-to-end with the real
database, context manager, suspicion checker and review queue, faking only the
two browser-driven clients — including that paused **and archived** conversations
are skipped entirely, that a money/PII reply is withheld and the conversation
paused **even with auto-pause disabled** (and that a safe reply is unaffected),
and that a repeated real platform id is answered only once
while a repeated content fingerprint is not suppressed across calls. The Playwright-driven clients (`signal_client`,
`chatgpt_client`, `facebook_scraper`) require a live browser and are exercised
manually. Run:

```bash
pip install -e ".[dev]"
pytest
```
