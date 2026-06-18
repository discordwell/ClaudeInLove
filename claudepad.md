# Claudepad — Session Memory

## Session Summaries (newest first)

### 2026-06-18T03:34:01Z — Maintenance pass: land stats + durable-dedup WIP, fix review-queue wrong-message bug
Two parts. First **landed the operator's staged WIP** (it was complete and
green): engagement stats (`src/core/stats.py` + `scripts/stats.py`, read-only
aggregation — engagements by status, in/out volume, time wasted, pending
reviews) and **durable cross-restart dedup** (`Database.has_inbound_message`
consulted from the main loop so a restart-emptied seen-set can't re-answer a
still-unread Signal message; scoped to real platform ids — content fingerprints
carry `IncomingMessage.synthetic_id=True` and stay on the per-session set so a
repeated "good morning" still gets a reply). Plus `get_all_scammers`,
`count_messages_by_direction`, `count_unreviewed_flags`, an
`idx_messages_platform_id` index, and a `_row_to_scammer` helper. Committed as
one unit (suite 71 → 84).

Then **fixed a real correctness bug in the human-review display** (suite 84 → 87):
- **`get_pending_reviews` showed the wrong message.** It used
  `get_messages(scammer_id, limit=5)[-1]` — the *most recent* message — as the
  flagged "their message". But a `SuspicionFlag` records the specific
  `message_id` it was raised against. With `auto_pause` disabled an outbound
  reply is stored *after* the flag, so the review showed **our own outbound
  reply labelled as the scammer's message**; with several flags on one scammer
  every row showed the same latest message; and a flag older than the 5 most
  recent wasn't even fetched. Reproduced via a throwaway script before fixing.
- **Fix.** Added `Database.get_message_by_id(message_id)` (precise PK lookup,
  `None` if absent) and made `get_pending_reviews` fetch
  `flag.message_id`. Also extracted `Database._row_to_message` (mirrors the
  WIP's `_row_to_scammer`) and reused it in `get_messages` — behavior-preserving
  (verified: `[f(r) for r in reversed(rows)]` == old `list(reversed([f(r)...]))`).
- **Tests (+3).** DB: `get_message_by_id` round-trips + returns None for a
  missing id. Queue: review shows the flagged message even when a newer outbound
  exists; two flags on one scammer each carry their own message.

Verified: `pytest` → 87 passed; two code-review finder sub-agents returned no
findings (refactor behavior-preserving, `flag.message_id` falsy-guard safe since
ids start at 1). Docs updated (ARCHITECTURE human-review note + test inventory).
Not pushed (handled separately).

### 2026-06-17T12:54:16Z — Maintenance pass: review-flag lifecycle (queue could never drain)
Fixed a real correctness bug in the human-review workflow (suite 65 → 71).

- **The review queue never drained.** `suspicion_log` has `human_reviewed` /
  `reviewed_at` columns and `get_unreviewed_flags()` filters
  `WHERE human_reviewed = FALSE`, but *nothing anywhere ever set them to TRUE*.
  Confirmed by grep across `src`/`scripts`. Consequence: `review_flagged.py`
  re-showed every flag ever created, on every run, forever — the reviewer could
  never clear handled items, and `reviewed_at` was permanently NULL.
- **Fix.** Added `Database.mark_flag_reviewed(flag_id)` (sets
  `human_reviewed = TRUE, reviewed_at = now`) and
  `HumanReviewQueue.mark_reviewed(flag_id)` delegating to it. Wired into
  `interactive_review_session`: **Resume** and **Pause** are both decisions, so
  they mark the displayed flag reviewed (per-flag granularity, by `flag_id`);
  **Skip** leaves it pending; **Quit** stops without touching the rest. Pause
  still keeps the scammer paused (that's `scammers.status`, separate from the
  flag's reviewed state). Also threaded `reviewed_at` back into the
  `SuspicionFlag` returned by `get_unreviewed_flags` (it was being dropped).
- **Tests (+6).** DB: `mark_flag_reviewed` drains only the named flag, leaves
  others. Queue/interactive: `mark_reviewed` clears pending; monkeypatched
  `input` proves Resume/Pause drain + Skip keeps pending. Verified the two
  interactive tests FAIL when the wiring is neutered, then restored to green.

Verified: `pytest` → 71 passed; `compileall` clean. Docs updated
(README review section, ARCHITECTURE suspicion_log + human-review notes). Not
pushed (handled separately).

### 2026-06-17T08:47:36Z — Maintenance pass: human-review usefulness + orchestration tests
Built on the prior pass. Three cohesive improvements, all verified by tests
(suite grew 56 → 65):

- **Withheld replies are now persisted for the reviewer.** Previously a flagged
  reply was printed to the console but never stored, so `review_flagged.py`
  showed score/reason + the scammer's message but NOT the text the bot wanted
  to send — the reviewer couldn't actually judge it. Added a
  `proposed_response` column to `suspicion_log`, threaded through `SuspicionFlag`,
  `Database.log_suspicion`/`get_unreviewed_flags`, `HumanReviewQueue`, and the
  interactive review display.
- **Idempotent SQLite migration.** `CREATE TABLE IF NOT EXISTS` never alters an
  existing table, so older local DBs would lack the new column. Added
  `Database._migrate()` / `_add_column_if_missing()` (PRAGMA-guarded
  `ALTER TABLE`), run from `connect()`. Identifiers are trusted literals only.
- **AI probes now escalate to a human.** In `main_loop.handle_incoming_message`,
  `quick_check()`'s probe detection was dead (logged, then discarded; the
  `# flag for review after` comment lied). Now an AI probe forces review even
  when the drafted reply scores below the suspicion threshold, and the stored
  outbound message's `was_flagged`/`flag_reason` use the same `should_review`
  decision (fixes a latent inconsistency on the probe-flagged-but-sent path).
- **Orchestration tests (new `tests/test_main_loop.py`).** `handle_incoming_message`
  had zero coverage. Added 7 end-to-end tests (real DB/context/suspicion/review,
  fake Signal+ChatGPT, delays forced to 0): happy path, paused-skip, empty
  response, flag+autopause withhold, flag-no-autopause send, AI-probe-forces-
  review, send-failure-no-outbound. Plus DB tests for the new column + migration.

Verified: `pytest` → 65 passed; `compileall` clean; code-review sub-agent found
no blockers (two nits addressed: migration-helper trust note + probe-test
comment). Not pushed (handled separately).

### 2026-06-10T19:50:21Z — Maintenance pass: tests + bug fixes + docs
Repo had **zero tests**. Added a full `pytest` suite (56 tests) for the
deterministic layers and fixed several real bugs found during review:

- **Signal dedup bug**: the no-DOM-id fallback hashed in `datetime.now()`, so a
  message got a new id every poll → the bot would re-answer the same message
  forever. Replaced with `SignalClient._message_fingerprint(sender, content)`
  (stable SHA-1, time-independent).
- **Human-review pause was in-memory + per-instance**: `review_flagged.py`
  (separate process) could never un-pause the running loop, and pauses died on
  restart. Now DB-backed via `scammers.status` (`is_paused/pause/resume` are
  async, reading/writing the DB). Added `set_scammer_status` /
  `get_scammer_status` / `get_paused_scammer_ids` to `Database`.
- **`.env.example` was stale** (listed OPENAI/ANTHROPIC/etc. keys the app never
  reads). Rewritten to match `config.py`.
- **Broken shutdown handler**: `asyncio.create_task(stop())` then `sys.exit(0)`
  meant `stop()` never ran. Replaced with `loop.add_signal_handler` → graceful
  teardown.
- Decoupled `suspicion_checker` from Playwright (TYPE_CHECKING import) so the
  safety logic is testable without a browser.
- Minor: cwd-independent `.env` loading; `ORDER BY timestamp DESC, id DESC` for
  deterministic message ordering; removed dead imports; `.gitignore` now covers
  `data/` (holds the SQLite DB + scraped persona) and tool caches.
- Added `ARCHITECTURE.md`; documented dev/testing in `README.md`.

Verified: `pytest` → 56 passed; `compileall` clean; code-review sub-agent found
no regressions. Not pushed (handled separately).

## Key Findings (persistent)

- **Project shape**: reactive scam-baiter. Polls the operator's own Signal
  Desktop (via CDP) for inbound scammer messages, drafts replies through the
  operator's own ChatGPT web session, screens them for AI tells, can pause for
  human review. Persona is built from the operator's *own* Facebook profile.
- **Testability floor**: the logic layer needs only `aiosqlite`, `python-dotenv`,
  and `rich`; Playwright is required only by the live clients
  (`signal_client`, `chatgpt_client`, `facebook_scraper`), which are
  manual/wet-test territory. `tests/conftest.py` redirects `DATA_DIR`/`LOG_DIR`
  to a temp dir before importing `src` (config + file log handler are built at
  import time).
- **Pause semantics**: pause = `scammers.status = 'paused'`; resume = `'active'`.
  `is_paused()` reads the DB so the loop, restarts, and the review tool agree.
- **Config**: all runtime knobs are env vars (see `.env.example`); `get_config()`
  is a cached global singleton.
- **Schema migrations**: `Database.connect()` runs `executescript(SCHEMA)` then
  `_migrate()`. New columns on existing tables must be added via
  `_add_column_if_missing()` (PRAGMA-guarded `ALTER TABLE`) since
  `CREATE TABLE IF NOT EXISTS` won't alter a live table. Migration steps must be
  idempotent and use trusted-literal identifiers only.
- **Review workflow**: flagged replies are withheld AND stored
  (`suspicion_log.proposed_response`) so `review_flagged.py` can show the exact
  text. The queue pairs each flag with the message it was raised against
  (`SuspicionFlag.message_id` → `Database.get_message_by_id`), not the latest
  message — otherwise a later reply or a second flag would mislabel what's under
  review. AI probes ("are you a bot?") force review regardless of heuristic score.
  Acting on a flag in the review tool (resume/pause) calls
  `Database.mark_flag_reviewed` → sets `human_reviewed`/`reviewed_at` so the flag
  leaves `get_unreviewed_flags()`; skip leaves it pending. Marking is per-flag
  (`flag_id`), independent of the scammer's pause state (`scammers.status`).
