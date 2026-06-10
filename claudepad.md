# Claudepad — Session Memory

## Session Summaries (newest first)

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
