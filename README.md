# TeleWire: Telegram SOCMINT Threat Intelligence Pipeline

TeleWire is a production-grade, real-time Telegram threat intelligence monitoring platform. It ingests messages asynchronously, performs advanced entity extraction, runs semantic zero-shot threat classification, clusters coordinated campaigns via vector embeddings, checks wallets against sanction blocklists, performs multimodal OCR & QR code decoding, evaluates composite risk scoring, visualizes forward network topologies, and supports analyst case briefing and reporting.

---

## 🚀 Quick Start (Local Sandbox)

### 1. Bootstrapping Environment
To configure your Python virtual environment, install package dependencies, initialize SQLite schemas, and run unit tests, execute:
```powershell
./scripts/dev_bootstrap.ps1
```
*Alternatively, install manual dependencies with:* `pip install -r requirements.txt`

### 2. Configure Environment `.env`
Copy the template `.env.example` to `.env` and fill in credentials:
```bash
copy .env.example .env
```
Key configurations:
*   `API_ID` & `API_HASH`: Obtain from https://my.telegram.org -> API Development Tools.
*   `PHONE`: The primary phone number linked to your Telegram account.
*   `ALERT_THRESHOLD`: Risk threshold (0-100) to trigger alarms (Default: `70`).
*   `ALERT_WEBHOOK_URL`: Optional endpoint for real-time JSON alert POST payloads.
*   `ALERT_TELEGRAM_BOT_TOKEN` & `ALERT_TELEGRAM_CHAT_ID`: Optional credentials to receive critical alarms directly in your Telegram chat.

### 3. Launch Ingestion Pipeline
To start the Telethon listener daemon and the Flask analyst interface:
```bash
python main.py
```
*Note: On your first execution only, the console will prompt you to enter the Telegram OTP code to authenticate. The session cache is written to `telegram_session.session` to bypass subsequent logins. For multi-account setups, authentication can also be initiated live on the web UI.*

*   **Flask Web UI Dashboard:** opens at **[http://localhost:5000](http://localhost:5000)**
*   **Streamlit Keyword Manager:** run `streamlit run keyword_manager.py` (opens at **[http://localhost:8501](http://localhost:8501)**).

### 4. Simulating Mock Activity (Sandbox Mode)
If you want to evaluate dashboard graphs, alert panels, and actor profiles without a live Telegram account, run:
```bash
python scripts/generate_mock_stream.py --delay 2.5
```
This script streams realistic target channels traffic, extracts test wallet addresses, runs semantic zero-shot classifiers, scores risk, updates profiles, and triggers dashboard warnings dynamically.

---

## 🛠️ System Architecture & Ingestion Flow

```
                                  +-----------------------+
                                  |   Telegram Clients    |
                                  | (Up to 5 accounts)    |
                                  +-----------+-----------+
                                              |
                                              | (NewMessage events)
                                              v
+-----------------------------------------------------------------------------------------+
| INGESTION LAYER (src/ingestion/)                                                        |
|                                                                                         |
|  +----------------------------+      +---------------------+      +------------------+  |
|  | PipelineManager (asyncio)  | ---> | TelegramListener(s) | ---> |  asyncio.Queue   |  |
|  +----------------------------+      +----------+----------+      +--------+---------+  |
|                                                 |                          |            |
|                                                 | (Active check)           |            |
|                                                 v                          v            |
|                                      +---------------------+      +------------------+  |
|                                      |  ActiveGroupCache   |      | Worker Pool (x5) |  |
|                                      +---------------------+      +--------+---------+  |
+----------------------------------------------------------------------------|------------+
                                                                             | (Thread Pool Executor)
                                                                             v
+-----------------------------------------------------------------------------------------+
| PROCESSING LAYER (src/processing/)                                                      |
|                                                                                         |
|   1. Deduplicator (SHA-256)                                                             |
|   2. Entity Extractor (wallets, UPIs, phones, emails, etc.)                             |
|   3. OFAC SDN Sanctions Matcher (XBT, ETH, TRX local cache)                             |
|   4. MediaProcessor (pytesseract OCR, pyzbar QR decode, pHash visual grouping)          |
|   5. SemanticProcessor (SentenceTransformers all-MiniLM-L6-v2, FAISS, Zero-shot NLP)    |
|   6. Threat Scoring Service (Composite risk scoring 0-100 & Telegram/Webhook Alerts)    |
+----------------------------------------------------------------------------|------------+
                                                                             |
                                                                             v
+-----------------------------------------------------------------------------------------+
| STORAGE & REPRESENTATION LAYERS (src/storage/ & src/dashboard/)                         |
|                                                                                         |
|   +--------------------------+     +------------------------+     +------------------+  |
|   |    SQLite (WAL Mode)     | <-> |  Flask Dashboard (:5000)| <-> |Streamlit Manager |  |
|   | (telegram_intel.db)      |     |  (Cytoscape graphs)    |     | (:8501, .pptx)   |  |
|   +--------------------------+     +------------------------+     +------------------+  |
|                 |                                                                       |
|                 +----------------> JSONL Backup Files (data/backup/YYYY-MM-DD.jsonl)    |
+-----------------------------------------------------------------------------------------+
```

### Threading & Concurrency Model

*   **Main Thread (asyncio loop):** Manages all active Telegram client connections, registers event handlers, and runs the watchdog reconnection loop.
*   **Listener Workers:** A pool of 5 asynchronous worker threads pulls messages from an ingestion queue to offload parsing.
*   **Thread Pool Executor:** Dedicated execution pool for CPU-bound extraction and blocking I/O (SQLite writes, image OCR, zero-shot classification, FAISS clustering).
*   **Flask Web Server:** Runs in a separate daemon thread sharing the WAL-enabled database.
*   **Streamlit Manager:** Spawns as a separate process for concurrent keyword CRUD operations.

---

## 💎 Feature Details & Technical Specifications

### 1. Ingestion Performance & Reliability
*   **High-Throughput listener (`src/ingestion/listener.py`):** Monitors joined channels, immediately queueing raw events in memory to prevent Telethon blockages.
*   **Worker Pool:** 5 parallel worker threads pull from the queue, committing message batches every 20 events or 500ms using transactional SQL `executemany` statements to bypass database bottleneck issues.
*   **Active Group Gate (`ActiveGroupCache`):** An in-memory set of monitored channel IDs resolves state instantly without initiating database reads.
*   **Reliable Watchdog & Reconnection:** Intercepts RPC/network failures. Implements exponential backoff (5s to 120s max). If rate limits hit, it sleeps the duration requested by Telegram (`FloodWaitError` seconds) and automatically performs a perfect gap backfill query on reconnect utilizing strictly monotonic message IDs (`last_message_id`).

### 2. Multi-Account Ingestion Control Center
*   **Pipeline Lifecycle Daemon (`src/ingestion/pipeline_manager.py`):** Manages concurrent Telethon clients (up to 5 distinct phone numbers) in parallel.
*   **Web-Based OTP Authentication:** Adds new phone numbers live from the dashboard, executing the OTP handshake sequence asynchronously and prompting the analyst via dynamic forms.
*   **Runtime Toggle:** Suspends/resumes update fetches across all streams via global flag changes without breaking Telegram socket connections.

### 3. Entity Extraction, Geolocation & Sanctions Audit
*   **Entity Extractor (`src/processing/entity_extractor.py`):** Validates and extracts phone numbers, emails, URLs, IP addresses, Telegram handles, crypto wallet addresses (BTC legacy/Bech32, Ethereum, TRON/TRC20, TON user-friendly), UPI IDs, IBANs, and credit card numbers.
*   **OFAC Sanctions Auditor (`src/processing/wallet_enricher.py`):** Automatically downloads and caches the US Treasury SDN lists (XBT, ETH, TRX) in the background. Matches extracted wallets against these records on ingest, raising immediate alerts for sanctioned hits.
*   **Blockchain Enriched Profile:** Background thread queries public blockchain APIs (Blockchair, TronGrid, TonCenter) for balances, transaction counts, and active timestamps, respecting rate limits via a 2-second sleep interval.
*   **Phone Carrier & Location Lookup:** Synchronously performs local geocoding lookups using the `phonenumbers` package. Resolves country, regional location/state, mobile carrier, and formatting correctness.

### 4. Zero-Shot NLP & FAISS Campaign Clustering
*   **Sentence Transformers (`src/processing/semantic_service.py`):** Vectorizes text and OCR extracts using `all-MiniLM-L6-v2` into 384-dimensional embeddings, caching the local model structure under `data/models/`.
*   **Zero-Shot Classifier:** Evaluates cosine similarity of message embeddings against pre-embedded threat definitions: Scam/Fraud, Weapons/Violent Extremism, Cybersecurity/Hacking, Financial Crimes/Money Mule, Drug Trafficking, and Legitimate.
*   **FAISS Campaign Clustering:** Queries a Cosine Similarity index (`faiss.IndexFlatIP`) mapping near-duplicate texts (similarity $\ge 0.85$) into consolidated `campaigns` rather than single messages, dramatically reducing analyst noise.

### 5. Multimodal OCR & Image Hashing
*   **OCR Text Parsing (`src/processing/media_processor.py`):** Automatically downloads attachments and extracts text from images utilizing PyTesseract.
*   **QR Scanner:** Extracts payment links and UPI information from QR codes using pyzbar.
*   **Perceptual Image Hashing:** Groups visual graphics via pHash (Hamming distance $\le 10$) using `imagehash.phash` to map coordinated visual spam campaigns.
*   **Automatic Storage Purge:** Deletes media assets older than 30 days or exceeding 5GB total cache, maintaining database references while cleaning local disk storage.

### 6. Threat Risk Scoring & Alarms Dispatcher
*   **Weighted Threat Risk Scorer (`src/processing/scoring_service.py`):** Calculates a composite score (0-100) combining sanctions list matches (+40), threat categories (+20 to +30), keyword match proximity (+15), campaign memberships (+10), and urgency language heuristics (+10).
*   **Real-time Dispatcher:** Issues warning payloads via Webhook POST requests and styled Telegram markdown alerts to configured endpoints if the risk score exceeds `ALERT_THRESHOLD`.

### 7. Directed Network Centralities & Temporal Profiling
*   **Topology Graph Builder (`src/processing/network_service.py`):** Formulates channel forward relationships into a directed network using `NetworkX`. Calculates PageRank centralities, in-degrees, and out-degrees, outputting elements for interactive Cytoscape.js layouts.
*   **Actor Profiling:** Calculates rolling averages of sender threat risk scores, classifying senders into Risk Tiers (Critical, High, Medium, Low).
*   **Timezone Inferences:** Maps posting timestamp histories into 24-hour UTC histograms to estimate the threat actor's timezone.

### 8. Case Builder Workspace
*   **Case Folders (`src/processing/reporting_service.py`):** Groups related findings (threat messages, wallets, and actor handles) into a single folder.
*   **Executive Intelligence Brief:** Generates and compiles a downloadable, styled executive summary in Markdown containing case inventory metrics, risk evaluations, and formatted message logs.

### 9. Group Discovery Scanner & Direct Joins
*   **Group Discovery Service (`src/ingestion/discovery_service.py`):** Runs an async background scan every 5 minutes.
  *   *Keyword searches:* Queries global public search results for configured threat words using `contacts.SearchRequest`.
  *   *Invite Link Extraction:* Pulls `t.me/+` invite links from ingested messages, using `CheckChatInviteRequest` to peek the group title and member count without joining.
*   **Analyst Review Pipeline:** Places discovered targets in a pending queue for approval. Clicking `✅ Start Monitoring` performs an auto-join, while `✕ Dismiss` rejects the target. Monitored groups can be exited via the `🚪 Leave` action button.

### 10. Heatmaps, Watchlists & Multi-Select Utilities
*   **Temporal Heatmap:** Draws a 7x24 canvas grid mapping posting counts and threat densities over week days/hours. Provides instant interactive dashboard filters on click.
*   **Multi-Select Dropdowns:** Replaces classic dropdown selectors with searchable, multi-value multi-select tags in Messages, Time Range, and Export tabs.
*   **Saved Watchlists:** Creates filter state bookmark presets to quickly load preset search queries.
*   **Live Translation:** Incorporates backend multi-language translation buttons inside the message detail drawer.

---

## 📁 Repository Directory Structure

```
TELEGRAM/
│
├── main.py                       # Main application startup, config loading, and loop initialization
├── keyword_manager.py            # Streamlit UI keyword tool (separate terminal)
├── migrate_db.py                 # Older standalone migration helper (deprecated; main.py migrates additively)
├── requirements.txt              # Application Python dependencies
├── README.md                     # General project documentation (This file)
├── PIPELINE.md                   # Operational technical flow reference and developer notes
├── Advanced_Features.md          # Project advancement roadmap
├── .env.example                  # Template configuration file for environmental secrets
│
├── config/
│   ├── config.yaml               # Runtime application parameters
│   └── keywords.txt              # Seed keywords loaded into SQLite on bootstrap
│
├── data/                         # Created automatically on first execution
│   ├── telegram_intel.db         # WAL-enabled SQLite database
│   ├── faiss_index.bin           # Saved FAISS index vector database
│   ├── faiss_mapping.json        # Mapping structure matching FAISS indices to message IDs
│   ├── media/                    # Local media cache directory
│   ├── models/                   # Local models cache directory
│   ├── sanction_lists/           # OFAC SDN local cache text files
│   └── backup/
│       └── YYYY-MM-DD.jsonl      # Raw JSONL daily message logging fallback
│
├── src/
│   ├── __init__.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── client.py             # Telethon builder, session authorization, and channel syncing
│   │   ├── listener.py           # Ingestion queue worker, active checks, and fwd_from parsing
│   │   └── pipeline_manager.py   # Multi-account configuration controller (up to 5 sessions)
│   ├── processing/
│   │   ├── __init__.py           # ProcessingEngine facade
│   │   ├── deduplicator.py       # Thread-safe SHA-256 hash duplication manager
│   │   ├── entity_extractor.py   # Regex extractors, checksum validators, and OFAC lists
│   │   ├── keyword_matcher.py    # RapidFuzz matcher, dynamic Hinglish thresholding, and backmatching
│   │   ├── media_processor.py    # PyTesseract OCR, pyzbar QR scanning, and pHash calculators
│   │   ├── network_service.py    # NetworkX directed graph PageRank calculations
│   │   ├── pptx_extractor.py     # Slide token extractor for Streamlit
│   │   ├── reporting_service.py  # Case Files Markdown generator
│   │   ├── scoring_service.py    # Composite 0-100 risk math and alarm webhook/bot dispatcher
│   │   ├── semantic_service.py   # all-MiniLM-L6-v2 zero-shot classification and FAISS clusters
│   │   └── wallet_enricher.py    # Blockchain API enrichment background thread
│   └── storage/
│       ├── __init__.py
│       └── database.py           # SQLite WAL settings, schema layouts, and migrations
│
├── static/
│   ├── style.css                 # Dark glassmorphism dashboard UI theme
│   └── dashboard.js              # Dashboard frontend routing and Cytoscape graphing logic
│
├── tests/                        # Full test suite covering application modules
│   ├── test_entities.py          # Entity patterns and checksum verification tests
│   ├── test_media.py             # OCR, QR, and pHash integration tests
│   ├── test_multi_account.py     # PipelineManager and account management tests
│   ├── test_network.py           # Directed forward graph and centrality tests
│   ├── test_pipeline.py          # Ingestion queue, batch writing, and backfill tests
│   ├── test_reporting.py         # Case Brief and reporting structure tests
│   ├── test_sandbox.py           # Sandbox mock data stream validation
│   ├── test_scoring.py           # Composite score calculations and webhook dispatch tests
│   └── test_semantics.py         # Zero-shot classification and FAISS clustering tests
```

---

## 🗄️ Database Schema Reference

The database uses SQLite optimized with **WAL mode**, `PRAGMA synchronous=NORMAL`, and page cache configuration.

### 1. Table: `messages`
Stores enriched threat message items, matching markers, and media details.
*   `id` (INTEGER, Primary Key): Auto-increment row ID.
*   `message_id` (INTEGER): Raw message ID from Telegram.
*   `group_name` (TEXT): Title of destination group.
*   `group_id` (INTEGER): Destination group/channel numeric ID.
*   `sender_name` (TEXT): Sender display name.
*   `sender_phone` (TEXT): Sender phone number (if visible).
*   `text` (TEXT): Full message body text.
*   `language` (TEXT): Detected language (e.g. `en`, `hi`, `ru`).
*   `is_forwarded` (INTEGER): `1` if forwarded; `0` otherwise.
*   `forward_from_name` (TEXT): Title of original source channel.
*   `forward_from_id` (INTEGER): Numeric ID of original source channel (ground-truth).
*   `matched_keyword` (TEXT): Best matching keyword phrase.
*   `fuzzy_score` (REAL): RapidFuzz score.
*   `is_matched` (INTEGER): `1` if fuzzy_score $\ge$ threshold; `0` otherwise.
*   `timestamp` (TEXT): ISO-8601 UTC timestamp.
*   `hash` (TEXT, Unique): Unique index code `SHA-256(message_id:group_id)`.
*   `campaign_id` (TEXT): Linked FAISS campaign cluster identifier.
*   `threat_category` (TEXT): Zero-shot classification result.
*   `media_path` (TEXT): Relative path to local media cache.
*   `ocr_text` (TEXT): Text extracted via PyTesseract.
*   `phash` (TEXT): Perceptual image hash.
*   `qr_codes` (TEXT): JSON list of extracted QR codes payloads.
*   `risk_score` (REAL): Composite threat score (0-100).
*   `fetched_by` (TEXT): Phone number of Telegram account that fetched this message.

### 2. Table: `groups`
Maintains monitored channels registry.
*   `id` (INTEGER, Primary Key): Row ID.
*   `group_id` (INTEGER, Unique): Numeric ID of Telegram entity.
*   `group_name` (TEXT): Display title.
*   `group_type` (TEXT): `'group'` or `'channel'`.
*   `is_active` (INTEGER): Monitoring state (`1` = active; `0` = inactive).
*   `member_count` (INTEGER): Participant quantity.
*   `last_message_at` (TEXT): ISO-8601 UTC timestamp of last processed message.
*   `last_message_id` (INTEGER): Highest Telegram message ID processed (backfill anchor).
*   `added_at` (TEXT): Registration timestamp.

### 3. Table: `keywords`
Monitored keyword rules registry.
*   `id` (INTEGER, Primary Key): Row ID.
*   `keyword` (TEXT, Unique, NOCASE): Tracked phrase.
*   `source` (TEXT): Origin tag (`manual`, `pptx`, etc.).
*   `added_at` (TEXT): Add timestamp.

### 4. Table: `pipeline_events`
Ingestion lifecycle status metrics.
*   `id` (INTEGER, Primary Key): Row ID.
*   `event_type` (TEXT): Event class (`startup`, `disconnect`, `reconnect`, `backfill`).
*   `started_at` (TEXT): Starting timestamp.
*   `ended_at` (TEXT): Termination timestamp.
*   `duration_seconds` (REAL): Event duration.
*   `details` (TEXT): Performance information (e.g. `"backfilled=42"`).

### 5. Table: `entities`
Normalized entity records.
*   `id` (INTEGER, Primary Key): Primary Key.
*   `entity_type` (TEXT): Entity category (e.g. `phone_number`, `crypto_btc`, `upi_id`).
*   `entity_value` (TEXT): Normalized string value.
*   *Unique Constraint:* `(entity_type, entity_value)`

### 6. Table: `message_entities`
Many-to-many relationship linking messages to entities.
*   `message_id` (INTEGER): FK referencing `messages(id)`.
*   `entity_id` (INTEGER): FK referencing `entities(id)`.
*   `position_in_text` (INTEGER): Starting position of string in raw text.

### 7. Table: `wallet_enrichments`
Stores details of crypto wallets parsed by blockchain API workers.
*   `entity_id` (INTEGER, Primary Key): FK referencing `entities(id)`.
*   `balance` (REAL): Current token balance.
*   `tx_count` (INTEGER): Transaction count.
*   `total_volume` (REAL): Total volume processed.
*   `first_active` (TEXT): First transaction timestamp.
*   `last_active` (TEXT): Last transaction timestamp.
*   `is_sanctioned` (INTEGER): `1` if present in OFAC SDN lists; `0` otherwise.
*   `enrichment_source` (TEXT): API name (e.g. `Blockchair`).
*   `last_enriched_at` (TEXT): Update timestamp.

### 8. Table: `phone_enrichments`
Stores offline carrier and location information parsed via the `phonenumbers` library.
*   `entity_id` (INTEGER, Primary Key): FK referencing `entities(id)`.
*   `country_code` (TEXT): Numeric calling code (e.g. `91` for India).
*   `country_name` (TEXT): Resolved country name (e.g. `India`).
*   `location` (TEXT): Resolved region/city details.
*   `carrier` (TEXT): Network operator name (e.g. `Airtel`, `Reliance Jio`).
*   `national_number` (TEXT): Phone number excluding country code.
*   `is_valid` (INTEGER): `1` if valid format; `0` if invalid.
*   `last_enriched_at` (TEXT): Update timestamp.

### 9. Table: `campaigns`
Stores coordinated campaign details.
*   `id` (TEXT, Primary Key): Campaign hash identifier.
*   `campaign_name` (TEXT): Human-readable name.
*   `first_seen_at` (TEXT): First message timestamp.
*   `last_seen_at` (TEXT): Last message timestamp.
*   `threat_category` (TEXT): Shared threat classification.
*   `representative_text` (TEXT): Snippet of text.

### 10. Table: `sender_profiles`
Sender risk aggregation tables.
*   `id` (INTEGER, Primary Key): Primary Key.
*   `sender_id` (TEXT, Unique): Telegram sender identifier.
*   `sender_phone` (TEXT): Sender phone (if visible).
*   `total_messages` (INTEGER): Messages sent.
*   `cumulative_risk` (REAL): Accumulated risk points.
*   `average_risk` (REAL): Average risk.
*   `last_seen_at` (TEXT): Last message timestamp.
*   `risk_tier` (TEXT): Classified tier (`Critical`, `High`, `Medium`, `Low`).

### 11. Table: `cases`
Analyst case compilation directories.
*   `id` (TEXT, Primary Key): Case UUID.
*   `title` (TEXT): Case folder header.
*   `description` (TEXT): Analyst executive overview.
*   `created_at` (TEXT): Creation timestamp.

### 12. Table: `case_items`
Maps message rows, crypto wallets, and actors to specific case folders.
*   `id` (INTEGER, Primary Key): Row ID.
*   `case_id` (TEXT): FK referencing `cases(id)`.
*   `item_type` (TEXT): `'message'`, `'wallet'`, or `'actor'`.
*   `item_value` (TEXT): Row ID or address value string.
*   `added_at` (TEXT): Mapping creation time.

### 13. Table: `watchlists`
Bookmarks filter metrics.
*   `id` (TEXT, Primary Key): Watchlist UUID.
*   `name` (TEXT): Title.
*   `query_params` (TEXT): JSON parameters.
*   `created_at` (TEXT): Creation timestamp.

### 14. Table: `telegram_accounts`
Monitored Telegram sessions credentials.
*   `phone` (TEXT, Primary Key): Phone number key.
*   `api_id` (INTEGER): Telegram app configuration identifier.
*   `api_hash` (TEXT): Telegram app configuration hash.
*   `session_name` (TEXT, Unique): File path to Telegram session on disk.
*   `is_active` (INTEGER): Monitoring flag.
*   `status` (TEXT): Connection state (`connected`, `disconnected`, `needs_otp`).

### 15. Table: `pending_groups`
Stores auto-discovered groups pending approval.
*   `id` (INTEGER, Primary Key): Auto-increment row ID.
*   `group_id` (INTEGER): Telegram group ID (if resolved).
*   `group_name` (TEXT): Real group name or invite link placeholder.
*   `group_username` (TEXT): Public handle username.
*   `member_count` (INTEGER): Resolving member count.
*   `invite_link` (TEXT): Parsed t.me/+ invite link.
*   `source` (TEXT): `'keyword_search'` or `'invite_link'`.
*   `source_keyword` (TEXT): Keyword that triggered search discovery.
*   `discovered_at` (TEXT): Discovery timestamp.
*   `status` (TEXT): `'pending'`, `'approved'`, `'dismissed'`.
*   `context_text` (TEXT): Context snippet of source message where found.

---

## 📊 Sidebar Navigation Workspaces & How They Work

### 🏠 1. Dashboard
*   **What it is:** High-level analytics console showing system stats cards, interactive metrics charts, and a **7x24 Temporal Activity Heatmap**.
*   **Under the Hood:** Invokes `/api/stats` aggregating message volume history, tracking active groups, showing keyword volume counts via Chart.js, plotting top active groups, and drawing a canvas activity density matrix. Click any timezone cell to filter the messages listing.

### 💬 2. Messages
*   **What it is:** Granular search engine spreadsheet displaying all ingested messages with multi-value filtering.
*   **Under the Hood:** Connects user queries to SQL search operations. Supports **Multi-Select dropdown filtering** for keywords and channels. Row colors indicate status: Green = Keyword Hit, Gold = Cross-Group Forward, Dark Amber = Both. Clicking a row slides open a detailed analyst card showcasing PyTesseract OCR text, decoded QR codes, extracted entities (wallets, phone lookups), and a **Side-by-Side IOC Pivot Drawer** (linked via double-click on highlights). Supports live **🌐 Multi-Language translation**.

### 🕐 3. Time Range
*   **What it is:** Search workspace focused on isolating narrow operational time intervals.
*   **Under the Hood:** Translates natural date inputs into UTC timestamps, performing SQLite indexed range scans. Offers one-click extraction exports.

### 👥 4. Groups
*   **What it is:** Registry console controlling monitored target groups, direct joining/searching, and the auto-discovery approval queue.
*   **Under the Hood:** Lists monitored dialogs. Allows manually joining public/private channels. Includes the **Auto-Discovered Groups** analyst workflow card panel (displaying real name/member peeks via `CheckChatInviteRequest` and found message text context) alongside a pulsing badge count (`🔍 N`). Monitored groups can be cleanly left using the **🚪 Leave** action button.

### 🔑 5. Keywords
*   **What it is:** Active keyword rules management interface.
*   **Under the Hood:** Displays chip clouds of keywords, dynamic effectiveness statistics (hit rates), and a match count table. Modifications are written to SQLite, triggering matcher updates within 60s and background retroactive matching on historic messages.

### 📥 6. Export
*   **What it is:** File compiler to extract data for downstream reporting.
*   **Under the Hood:** Packages filtered data into styled Excel files (`openpyxl`), highlighting threat rows, creating Legend worksheets, and summarizing metrics.

### 📢 7. Campaigns
*   **What it is:** Cluster grouping of coordinated spam or scams.
*   **Under the Hood:** Groups near-duplicates using cosine similarity of embeddings ($\ge 0.85$) and visual similarity of images via pHash ($\le 10$).

### 🕸️ 8. Network Intel
*   **What it is:** Forwards topology network visualizer and posting cadences.
*   **Under the Hood:** Builds a directed graph of channel forwards. Calculates PageRank via NetworkX and feeds elements to Cytoscape.js. Renders posting frequency histograms.

### 👤 9. Actor Profiles
*   **What it is:** Sender risk tracking dashboard.
*   **Under the Hood:** Aggregates message counts and risks into Low, Medium, High, and Critical Risk Tiers. Displays temporal activity histograms to infer the actor's timezone.

### 📁 10. Case Files
*   **What it is:** Evidence compiler workspace.
*   **Under the Hood:** Links target elements (messages, wallets, actor handles) to Case IDs. Generates formatted Executive Intelligence Brief Markdown reports.

### 🩺 11. Pipeline Health
*   **What it is:** System health status monitor.
*   **Under the Hood:** Displays disconnect metrics, daily downtime lengths, and details from the `pipeline_events` log.
*   **Ingestion Control Center:** Analyst interface to register, start, stop, or delete up to 5 concurrent Telegram sessions. Facilitates SMS OTP connections.

---

## 🛠️ Operational Runbooks & Operations Guide

### Runbook A: Setting Up a New Telegram Session
1. Navigate to **Pipeline Health** -> **Ingestion Control Center**.
2. Input the spare account details: Phone (International format: e.g. `+919876543210`), API ID, and API Hash. Click **Add Account**.
3. Telethon will request a login code. The status changes to `needs_otp`.
4. Locate the dynamic input form on the dashboard. Enter the Telegram OTP code received and click **Verify OTP**.
5. The session is cached as `data/telegram_session_phone.session` and starts monitoring.

### Runbook B: Keyword Hot-Reloading & Retroactive Back-Matching
*   **Adding Keywords:** Dashboard -> **Keywords** -> Type word and press Enter (or upload `.pptx` via Streamlit).
*   **Automatic Reload:** The ingestion engine detects database additions every 60 seconds.
*   **Back-Matching:** The matcher spawns a background thread querying up to 1,000 unmatched messages, retroactively matching them against new rules.

### Runbook C: Database Backups & Safe Copying
Since SQLite runs in **WAL mode**, reader connections do not block writing threads. It is safe to copy the database file directly during live execution:
```bash
copy data\telegram_intel.db data\telegram_intel_backup_%date:~-4,4%%date:~-10,2%%date:~-7,2%.db
```

### Runbook D: Disaster Recovery (Raw Backup Import)
If database corruption occurs:
1. Stop the application via `Ctrl+C`.
2. Delete the database file: `del data\telegram_intel.db`.
3. Start the application: `python main.py` (Creates schema).
4. Run the backup recovery utility importing records from the raw daily logging files:
   ```bash
   python -c "
   import json, os, sqlite3
   conn = sqlite3.connect('data/telegram_intel.db')
   # Read backup JSONL files and insert messages ...
   "
   ```

---

## 🧪 Unit Tests Validation

TeleWire includes unit tests verifying all features. Run the tests using the bootstrap wrapper or python discover:
```bash
python -m unittest discover -s tests
```
*Expected output shows all tests passing successfully.*
