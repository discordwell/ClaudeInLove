# Claudepad — Session Memory

## Session Summaries (newest first)

### 2026-06-24T00:00:00Z — Maintenance pass: enforce "never send money/PII" in code (ContentGuard)
One cohesive safety improvement (suite 99 → 158, +59). Closed the biggest latent
risk in the system: the project's central invariant — *"waste time, never send
money or real personal data"* — existed **only as prose** in `SYSTEM_PROMPT` and
the persona template. There was **zero programmatic enforcement**. The
`suspicion_checker` only screens for *AI tells*, not invariant violations.

- **Reproduced the hole first.** A reply that literally agrees to wire $500 via
  Western Union *and* includes an SSN scores **0.00** on `suspicion_checker`
  (it's casual + human-sounding) and would be auto-sent — the exact worst case,
  against a counterparty actively trying to extract money/PII.
- **New `src/safety/content_guard.py`** (pure regex, no deps, browser-free like
  `suspicion_checker`). `ContentGuard.check(reply) -> GuardResult(is_safe,
  violations)`. Two axes: (1) **money commitment** — affirmative "I'll
  send/wire/transfer/pay/deposit … money/$/gift cards/crypto/fee", payment-app
  use ("venmo you"), buying gift cards, "the money is on its way", and an
  unambiguous-money-verb+bare-amount rule ("wire the 500"); (2) **PII** — SSN,
  13+ digit card/account runs, labelled bank numbers, ETH/BTC wallets.
- **Precision-first** (the persona *must* discuss money to stall). Money checks
  run **clause by clause** (`_CLAUSE_SPLIT` on `.!?;,`/`but`/`though`), skip any
  clause with a negation (`can't`, `won't`, `not sending`, …), and require the
  verb+object within ~3 words. So deflections ("my account's frozen", "I can't
  send anything") and hyperbole ("the 100 reasons I love you, but not a dime")
  pass; only real commitments trip it.
- **Integration (`main_loop.handle_incoming_message`).** Guard runs alongside
  the suspicion check. A violation **always** withholds + pauses, overriding
  `auto_pause_on_flag` (the opt-out governs AI-suspicion flags, not hard-safety
  ones) via new `HumanReviewQueue.flag_for_review(force_pause=...)`; logged score
  floored to 1.0 so it sorts to the top of the review queue; reason leads with
  `SAFETY: …`.
- **Tests (+59).** `test_content_guard.py`: recall (money + PII blocked) and
  **precision** (ordinary chatter, deflections, phone numbers, hyperbole pass),
  plus an adversarial-corpus assertion that the dangerous reply is invisible to
  the suspicion checker (so the block is attributable to the guard). Main-loop
  integration: withheld+paused even with auto-pause off; safe reply unaffected.
  `flag_for_review(force_pause=True)` overrides auto-pause-off.

Verified: `pytest` → 158 passed; `compileall` clean; neuter-test (gut the guard
→ 15 tests fail, restore → green); ReDoS check (linear time, 109ms on a 208KB
input); end-to-end wet test drove a dangerous reply through the full pipeline →
withheld, paused, top-priority flag with both violations in the reason.
Code-review sub-agent: no blockers; found a real recall gap (negation suppressed
the *whole* sentence, so "warm capitulations" like "I shouldn't, but I'll send
the money" leaked) → fixed with clause-splitting + bare-amount rule, both pinned
by new must-block tests. Docs updated (README safety section + diagram,
ARCHITECTURE module map/design points/testing). Not pushed (orchestrator
handles that).

### 2026-06-23T00:00:00Z — Maintenance pass: activate the dormant operator-notes feature
One cohesive improvement (suite 91 → 99). Turned a fully-plumbed-but-dead
capability into a working operator tool.

- **`scammers.notes` was injected into the prompt but never written.**
  `build_full_prompt` already adds `[Notes about this scammer: ...]` (and a test,
  `test_full_prompt_includes_incoming_message_and_notes`, pins it), the column
  exists, `_row_to_scammer` reads it, and `update_scammer` can write it — but a
  grep proved *no code path ever set it*. So the prompt-steering feature could
  never fire: notes were always `None`. Diagnosed as a half-implemented feature,
  not a bug per se.
- **Added focused DB accessors.** `Database.set_scammer_notes` /
  `get_scammer_notes` (single-column read/write, mirroring the
  `set_scammer_status`/`get_scammer_status` pattern — minimal blast radius vs.
  introducing a new `get_scammer_by_id`).
- **`HumanReviewQueue.add_note`** appends a note newline-separated (observations
  accumulate across sessions and all flow into the prompt), ignores blank/
  whitespace input (no stray blank line), returns the combined blob. Explicitly
  *not* a review decision: it never touches `scammers.status` or marks a flag
  reviewed.
- **Review tool wiring.** `get_pending_reviews` now carries `notes`;
  `interactive_review_session` shows existing notes and gains a **[N]ote**
  action. Restructured the per-flag prompt into a `while True` loop so Note
  re-prompts for a real action afterwards (the flag still needs a decision);
  r/p/a/q and skip/unknown all preserve their old behavior exactly.
- **Tests (+8).** DB notes round-trip + unknown→None; `add_note` appends &
  ignores blanks; note doesn't change status/flags; pending-reviews includes
  notes; interactive note-then-resume saves the note + drains the flag;
  interactive blank-note-then-skip adds nothing + leaves the flag pending; and
  an end-to-end test that two accumulated notes both reach `build_full_prompt`
  (the headline value — notes steering replies). Added a `_scripted_input`
  helper for multi-prompt interactive flows.
- **Code-review follow-ups (2 finders + the review itself).** Review confirmed
  the loop rewrite preserves every original branch (incl. quit skipping the
  trailing print) and found no bugs. Took two suggestions: (1) the end-to-end
  prompt test above; (2) hardened `_scripted_input` to raise a clear
  `AssertionError` on exhaustion instead of an opaque PEP-479 "coroutine raised
  StopIteration". Left the re-prompt-after-note loop as-is (unbounded only under
  pathological constant 'n' input; re-prompting is the correct UX since the flag
  still needs a decision).

Verified: `pytest` → 99 passed; `compileall` clean; neuter-test proved the two
key tests fail when `add_note` is gutted, then restored → green; wet-test drove
the interactive session (note added → resumed) and confirmed the note then
appears in the next `build_full_prompt` output. Docs updated (README review
options, ARCHITECTURE human-review note + module map + test inventory). Not
pushed (orchestrator handles that).

### 2026-06-18T11:08:15Z — Maintenance pass: conversation lifecycle (archive) + fix latent auto-respond gate
One cohesive improvement (suite 87 → 91). Completed a dead enum value and fixed
a latent correctness bug in the same stroke.

- **Latent bug: the loop auto-replied to any non-paused status.**
  `handle_incoming_message` gated on `review_queue.is_paused()` (status ==
  PAUSED), so a conversation in *any* other non-active state would still get an
  automatic reply. Changed the gate to `scammer.status == ScammerStatus.ACTIVE`
  (using the status already on the row `get_or_create_scammer` just returned —
  no extra DB read). Now paused **and** archived (and the reserved `flagged`)
  all correctly suppress the bot. Proved it's a real guard: temporarily reverted
  the gate to `is_paused` and the new archived-skip test FAILED (bot generated +
  "sent" a reply to an archived scammer), restored → green.
- **Completed the unreachable `ARCHIVED` status.** `ScammerStatus.FLAGGED` /
  `ARCHIVED` were defined but never set anywhere (only ACTIVE/PAUSED reachable).
  Added `HumanReviewQueue.archive()` (status → ARCHIVED; distinct from pause =
  temporary hold) and an `[A]rchive` action to `interactive_review_session`
  (archive + `mark_reviewed`, a terminal decision that drains the flag like
  Resume/Pause). Archive retires a burned/finished conversation; the active-only
  gate means it's never auto-answered again unless resumed.
- **`get_pending_reviews` now reports the real `status`** (active/paused/
  archived) instead of only an `is_paused` boolean, so the reviewer can tell an
  archived conversation from a live one. Kept `is_paused` (derived from the same
  single status read) for back-compat. Review tool shows `status.upper()`.
- **Consistency:** `get_active_scammers` now parametrizes `ScammerStatus.ACTIVE
  .value` instead of a hardcoded `'active'` literal (every other status query
  already does; behavior-identical).
- **Tests (+4):** `test_archived_scammer_is_skipped_entirely` (main loop),
  `test_archive_persists_to_db`, `test_get_pending_reviews_reports_archived_status`,
  `test_interactive_archive_marks_flag_reviewed_and_archives`; plus a `status`
  assertion on the existing pause-state review test.

Verified: `pytest` → 91 passed; `compileall` clean; review sub-agent found no
blockers/should-fix (only nits — took the redundant-DB-read one). Docs updated
(README review section + lifecycle, ARCHITECTURE gate/lifecycle + test
inventory). Not pushed (orchestrator handles that).

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
- **Lifecycle semantics**: `scammers.status` ∈ active/paused/archived/flagged
  (flagged reserved/unused). pause = `'paused'` (temporary hold), resume =
  `'active'`, archive = `'archived'` (retired/finished). The main loop
  auto-replies **only when status == ACTIVE** — gating on "is it active?" (not
  just "is it paused?") so every non-active state suppresses the bot; it reads
  the status straight off the row `get_or_create_scammer` returns. `is_paused()`
  reads the DB so the loop, restarts, and the review tool agree. The review tool
  offers Resume/Pause/Archive (all terminal decisions → `mark_flag_reviewed`) +
  Skip (leave pending).
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
- **Two-layer reply screening (`safety/`)**: `suspicion_checker` answers "does
  this sound like an AI?" (heuristic + optional LLM, score vs.
  `suspicion_threshold`). `content_guard` answers the *different* question "would
  this reply break the hard invariants?" — never commit to sending money, never
  emit PII (SSN/card/account/crypto-wallet). They are independent: a casual
  "sure I'll wire you $500" scores ~0 on suspicion yet must be blocked, so the
  guard runs regardless of score. A guard violation is authoritative: it
  **always** withholds + pauses, overriding `auto_pause_on_flag`
  (`flag_for_review(force_pause=True)`). Guard is precision-first and pure regex:
  money checks are clause-split + negation-skipping (deflections like "I can't
  send money" are the persona working as intended and must pass); PII checks run
  on the whole reply. Adding/loosening a money pattern? Re-run the precision
  corpus in `test_content_guard.py` — false positives cripple the bot's
  autonomy, not just its safety.
- **Operator notes (`scammers.notes`)**: free-text the operator attaches to a
  conversation via the review tool's **[N]ote** action
  (`HumanReviewQueue.add_note` → `Database.set_scammer_notes`). Notes append
  newline-separated and are injected into every reply by `build_full_prompt`
  (`[Notes about this scammer: ...]`) to keep the persona consistent (claimed
  backstory, money asks). Taking a note is *not* a review decision — it leaves
  `status` and the flag's reviewed state untouched and re-prompts for an action.
  Was a dormant feature before (prompt read it, nothing wrote it).
