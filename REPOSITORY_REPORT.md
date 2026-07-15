# Telegram Intelligence Pipeline - Repository Report

Generated on: 2026-07-03

## Executive Summary

This repository contains a Python-based Telegram intelligence monitoring pipeline. It uses Telethon to ingest messages from Telegram groups/channels in real time, processes messages through deduplication, language detection, and fuzzy keyword matching, stores enriched records in SQLite, writes JSONL backups, and exposes results through a Flask dashboard. A separate Streamlit keyword manager allows live keyword CRUD and keyword extraction from `.pptx` files.

The project is operationally oriented rather than a library package. Runtime artifacts such as `.env`, `telegram_session.session`, SQLite database files, JSONL backups, and `__pycache__` folders are present in the working directory.

## Repository Status

- Current directory: `C:\Users\visha\Videos\PHQ\SOCMINT\TELEGRAM`
- Git status: this folder is not currently a Git repository.
- Main entry point: `main.py`
- Main documentation: `README.md`, `PIPELINE.md`
- Main dashboard URL: `http://localhost:5000`
- Keyword manager command: `streamlit run keyword_manager.py`

## Technology Stack

| Area | Tools / Libraries |
|---|---|
| Telegram ingestion | `telethon` |
| Web dashboard | `flask` |
| Keyword manager | `streamlit`, `pandas` |
| Fuzzy matching | `rapidfuzz` |
| Language detection | `langdetect` |
| Storage | `sqlite3`, SQLite WAL mode |
| Export | `openpyxl`, CSV |
| Config/env | `pyyaml`, `python-dotenv` |
| PPTX parsing | `python-pptx` |

Dependencies are listed in `requirements.txt`.

## High-Level Architecture

The system is organized as a five-layer pipeline:

1. Sources: Telegram groups/channels the authenticated account has joined.
2. Ingestion: Telethon async client listens for `events.NewMessage`.
3. Processing: deduplication, language detection, fuzzy keyword matching.
4. Storage: SQLite database with WAL mode plus JSONL daily backups.
5. Presentation: Flask dashboard and Streamlit keyword manager.

The main async event loop runs Telethon and the watchdog. Flask runs in a daemon thread. Streamlit runs as a separate process when needed.

## Key Files and Directories

| Path | Purpose |
|---|---|
| `main.py` | Application startup, config loading, database init, Telegram client startup, dashboard thread startup, watchdog reconnect loop, gap backfill. |
| `keyword_manager.py` | Streamlit UI for adding/removing keywords and extracting candidates from `.pptx` decks. |
| `migrate_db.py` | Older standalone migration helper. It contains a hard-coded path from a previous machine/location. |
| `README.md` | Quick-start documentation and feature overview. |
| `PIPELINE.md` | Detailed architecture, startup flow, schema notes, troubleshooting, runbook, and update notes. |
| `requirements.txt` | Python package dependencies. |
| `config/config.yaml` | Runtime configuration: threshold, DB path, backup path, dashboard host/port, session name, reload interval. |
| `config/keywords.txt` | Seed keywords loaded into the database on startup. |
| `src/ingestion/client.py` | Builds and authenticates the Telethon client; syncs dialogs into the groups table. |
| `src/ingestion/listener.py` | New-message listener, active group cache, JSONL backup writer, forward-source extraction, async queue worker. |
| `src/processing/__init__.py` | `ProcessingEngine` facade tying deduplication, language detection, and keyword matching together. |
| `src/processing/deduplicator.py` | Thread-safe in-memory hash set warmed from existing DB messages. |
| `src/processing/lang_detector.py` | Deterministic `langdetect` wrapper with fallback to `unknown`. |
| `src/processing/keyword_matcher.py` | RapidFuzz matcher, live keyword reload, dynamic threshold for non-English text, retroactive matching for new keywords. |
| `src/processing/pptx_extractor.py` | Extracts cleaned keyword candidates from PowerPoint slide text. |
| `src/storage/database.py` | SQLite schema, migrations, DB connection helper, message/group/keyword/event operations. |
| `src/dashboard/app.py` | Flask app factory. |
| `src/dashboard/routes.py` | Dashboard API routes, health route, CSV/Excel export endpoints. |
| `src/dashboard/exporter.py` | CSV/Excel export builder and cross-group forward detection. |
| `src/dashboard/templates/index.html` | Single-page dashboard template. |
| `static/style.css` | Dashboard styling. |
| `static/dashboard.js` | Dashboard frontend logic. |
| `data/telegram_intel.db` | Runtime SQLite database. |
| `data/backup/*.jsonl` | Daily JSONL message backups. |
| `.env` | Runtime credentials. This should be treated as sensitive. |
| `telegram_session.session` | Telethon session file. This should be treated as sensitive. |

## Startup Flow

When `python main.py` runs:

1. `.env` and `config/config.yaml` are loaded.
2. The process changes working directory to the project root.
3. SQLite is initialized through `init_db()`.
4. Additive migrations are applied if expected columns are missing.
5. Seed keywords from `config/keywords.txt` are inserted with `INSERT OR IGNORE`.
6. `ProcessingEngine` is created.
7. Deduplicator warms up by loading all known message hashes from SQLite.
8. Keyword matcher loads keywords from the DB.
9. Telethon client is built from `API_ID`, `API_HASH`, and `PHONE`.
10. The client authenticates. First run requires OTP; later runs use `telegram_session.session`.
11. Dialogs are synced into the `groups` table.
12. Active groups are cached in memory.
13. Flask dashboard starts in a daemon thread.
14. The watchdog loop registers the message listener and waits for disconnects.
15. On reconnect, the watchdog resyncs dialogs and backfills gaps.

## Message Processing Flow

For each incoming Telegram message:

1. The listener receives a Telethon `NewMessage` event.
2. The active-group cache decides whether the group/channel is being monitored.
3. The event is placed into an `asyncio.Queue`.
4. A background worker extracts metadata:
   - message ID
   - group ID/name
   - sender name/phone if available
   - message text or caption
   - forwarded flag
   - forward source name/id when Telethon exposes it
   - UTC timestamp
5. CPU and blocking work is offloaded with `run_in_executor`.
6. `ProcessingEngine` creates a SHA-256 hash from `message_id:group_id`.
7. Duplicate hashes are ignored.
8. Language is detected with `langdetect`.
9. Keywords are matched with `rapidfuzz.fuzz.partial_ratio`.
10. Enriched messages are inserted into SQLite with `INSERT OR IGNORE`.
11. The deduplication set is updated after successful insert.
12. A JSONL backup line is written when backups are enabled.
13. Keyword hits are logged.

## Keyword Matching Behavior

- Default fuzzy threshold: `85`.
- Non-English messages use a lower threshold of `72`.
- Keywords are reloaded from the database every `keyword_reload_interval` seconds, currently `60`.
- When new keywords are detected during reload, a background retroactive match scans up to the last 1,000 unmatched messages and updates matches if the new keyword hits.
- Seed keywords currently include crypto/fraud terms such as `crypto`, `bitcoin`, `ethereum`, `scam`, `fraud`, `investment`, `pump`, `signal`, `airdrop`, `token`, `wallet`, `seed phrase`, and `private key`.

## Database Design

The database uses SQLite with:

- `PRAGMA journal_mode=WAL`
- `PRAGMA synchronous=NORMAL`
- `check_same_thread=False` on per-operation connections
- additive migrations on startup

### Tables

| Table | Purpose |
|---|---|
| `messages` | Stores enriched Telegram messages, matching results, forward metadata, timestamps, and unique hash. |
| `groups` | Stores synced groups/channels, active monitoring state, member count, and backfill anchors. |
| `keywords` | Stores tracked keywords with source and added timestamp. |
| `pipeline_events` | Stores startup, disconnect, reconnect, and health-related events. |

### Important Message Columns

- `message_id`
- `group_id`
- `group_name`
- `sender_name`
- `sender_phone`
- `text`
- `language`
- `is_forwarded`
- `forward_from_name`
- `forward_from_id`
- `matched_keyword`
- `fuzzy_score`
- `is_matched`
- `timestamp`
- `hash`

### Important Group Columns

- `group_id`
- `group_name`
- `group_type`
- `is_active`
- `member_count`
- `last_message_at`
- `last_message_id`
- `added_at`

## Current Local Data Snapshot

The local SQLite database exists at `data/telegram_intel.db`.

| Metric | Value |
|---|---:|
| Messages | 3,467 |
| Keyword-matched messages | 2,727 |
| Forwarded messages | 3,150 |
| Groups/channels | 24 |
| Keywords | 20 |
| Pipeline events | 14 |
| First stored message timestamp | `2026-06-29T06:22:31+00:00` |
| Latest stored message timestamp | `2026-07-03T05:57:54+00:00` |

This report intentionally does not include message contents, Telegram credentials, phone numbers, session data, or backup contents.

## Dashboard Features

The Flask dashboard exposes:

- Dashboard stats and charts.
- Message search/filtering by keyword, group, time range, and matched-only state.
- Group listing and live active/inactive toggles.
- Keyword listing, add, and delete endpoints.
- Pipeline health endpoint.
- CSV export.
- Styled Excel export.
- Health check endpoint at `/health`.

Relevant routes include:

| Route | Purpose |
|---|---|
| `/` | Dashboard page. |
| `/api/messages` | Paginated filtered messages. |
| `/api/stats` | Aggregate dashboard stats. |
| `/api/groups` | Group list. |
| `/api/groups/<group_id>/toggle` | Toggle monitoring state. |
| `/api/keywords` | List/add keywords. |
| `/api/keywords/<keyword>` | Delete keyword. |
| `/api/pipeline/health` | Pipeline health events. |
| `/export/csv` | CSV export. |
| `/export/excel` | Excel export. |
| `/health` | Basic health response. |

## Export and Cross-Group Forward Detection

Exports are implemented in `src/dashboard/exporter.py`.

CSV export includes human-readable headers and Yes/No fields.

Excel export includes:

- `Messages` sheet
- `Legend` sheet
- `Summary` sheet
- frozen header row
- styled headers
- row highlighting

Cross-group forwards are detected in two passes:

1. Ground-truth pass using `forward_from_id`.
2. Text fallback pass using normalized message text when `forward_from_id` is unavailable.

Highlight priority:

- Both keyword hit and cross-group forward: dark amber.
- Cross-group forward only: amber/gold.
- Keyword hit only: dark green.
- Neither: no fill.

## Reliability Features

- Watchdog reconnect loop around Telethon.
- Exponential reconnect backoff from 5 seconds up to 120 seconds.
- Special handling for `FloodWaitError`, sleeping for Telegram's specified delay.
- Gap backfill after reconnect.
- Backfill prefers `last_message_id` as a strict monotonic anchor.
- Falls back to `last_message_at` when no last ID is available.
- Pipeline event logging for disconnect/reconnect visibility.
- JSONL raw backup per UTC day.
- SQLite WAL mode to reduce read/write blocking between listener, dashboard, and Streamlit.

## Security and Privacy Notes

Sensitive runtime files are present in the project root:

- `.env`
- `telegram_session.session`
- `telegram_session.session-journal`
- `data/telegram_intel.db`
- `data/backup/*.jsonl`

These files may contain credentials, Telegram session material, sender metadata, message text, phone numbers, and intelligence data. They should not be committed to version control or shared casually.

Recommended `.gitignore` entries if this project is put under Git:

```gitignore
.env
.venv/
__pycache__/
*.pyc
*.session
*.session-journal
data/*.db
data/*.db-*
data/backup/
```

## Operational Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Run pipeline:

```bash
python main.py
```

Run keyword manager:

```bash
streamlit run keyword_manager.py
```

Open dashboard:

```text
http://localhost:5000
```

## Notable Implementation Details

- `main.py` calls `os.chdir(ROOT)` so relative paths resolve consistently.
- The listener avoids per-message DB reads for active group checks by using `ActiveGroupCache`.
- The message listener uses an async queue so Telethon event handling is kept lightweight.
- Database writes and processing are pushed into the default executor to avoid blocking the async event loop.
- Deduplication is based on `SHA-256(message_id:group_id)`.
- The DB schema migrates additively on startup.
- Dashboard group toggles update both SQLite and the in-memory group cache.
- `.pptx` extraction lowercases tokens, removes stop words, filters short/non-letter tokens, and deduplicates candidates.

## Risks and Issues to Address

1. Sensitive files are stored directly in the working tree.
   Add a `.gitignore` before initializing or pushing a Git repository.

2. `migrate_db.py` contains a hard-coded old path:
   `c:\Users\vivek\Desktop\TELEGRAM`.
   The main application already performs migrations, so this script should be updated or removed to avoid accidental misuse.

3. The README references `.env.example`, but no `.env.example` file is currently present.
   Add a template file with placeholder values only.

4. Re-registering listeners after reconnect may risk duplicate handlers because each watchdog iteration creates a new `TelegramListener` instance.
   The current `remove_event_handler` logic only removes a handler known to the same instance.

5. There is no automated test suite in the repository.
   High-risk areas worth testing first are database migrations, date filters, keyword matching thresholds, export annotation, and reconnect/backfill behavior.

6. Runtime artifacts such as `__pycache__`, `.venv`, database files, backups, and session files are mixed with source files.
   This is workable locally, but a cleaner source/runtime split would make maintenance safer.

7. The source files contain some mojibake/encoding artifacts in comments and documentation output.
   The code still runs, but cleaning the text encoding would improve maintainability.

## Recommended Next Steps

1. Add `.gitignore`.
2. Add `.env.example`.
3. Fix or remove `migrate_db.py`.
4. Review watchdog listener registration to guarantee only one active handler and worker exist after reconnects.
5. Add focused tests for storage, processing, exporters, and route filters.
6. Keep runtime data outside the repository when possible.
7. Add a short operator checklist for safe startup, shutdown, backup, and credential rotation.

## Overall Assessment

The repository is a functional real-time Telegram monitoring system with thoughtful operational features: WAL-backed SQLite storage, JSONL backups, active group caching, live keyword reload, retroactive matching, reconnect handling, and export workflows. The most important improvements are around repository hygiene, credential/session safety, test coverage, and tightening listener lifecycle behavior during reconnects.
