# Telegram Intelligence Pipeline — Advancement Roadmap

**Prepared for:** Antigravity implementation handoff
**Date:** 2026-07-03
**Source repo:** Telegram Intelligence Pipeline (`main.py`, Telethon + SQLite + Flask)

This document lists every feature to implement, grouped by priority. Each item includes what it is, why it matters, and concrete implementation notes. Phase 0 is bug fixes — these must land before anything else, since new features (embeddings, entity extraction) will otherwise run on duplicated/corrupted data from the existing listener bug.

---

## Phase 0 — Critical Fixes (do first, before any new feature)

### 0.1 Fix duplicate event handler leak on reconnect
**Problem:** Every watchdog reconnect creates a new `TelegramListener` instance and registers a new handler. `remove_event_handler` only removes handlers known to the *same* instance, so old handlers accumulate across reconnects — messages get processed 2x, 3x, Nx after repeated disconnects.
**Fix:** Maintain a single module/client-level registry of active handlers. On reconnect, explicitly deregister *all* previously registered handlers (not just the current instance's) before registering the new one. Consider making the listener a singleton that re-binds rather than re-instantiates.

### 0.2 Move from single-consumer queue to worker pool
**Problem:** One `asyncio.Queue` + one background worker means bursts (many messages across 24 groups at once) back up behind a single consumer.
**Fix:** 3–5 worker coroutines pulling from the same bounded queue. Add backpressure logging when the queue nears capacity so lag is visible, not silent.

### 0.3 Batch database writes
**Problem:** One `INSERT OR IGNORE` transaction per message causes unnecessary write overhead under burst load.
**Fix:** Buffer incoming enriched messages and flush via `executemany` every ~500ms or every 20 messages (whichever comes first), inside a single transaction.

### 0.4 Dedicated thread pool for ingestion work
**Problem:** `run_in_executor` currently shares Python's default executor across DB writes, language detection, and fuzzy matching — no isolation from other work.
**Fix:** Create a dedicated `ThreadPoolExecutor` sized for ingestion throughput, separate from any other executor usage.

### 0.5 Tune SQLite WAL settings for current load
Review and set explicitly: `PRAGMA wal_autocheckpoint`, `PRAGMA cache_size`, `PRAGMA mmap_size`. Benchmark checkpoint frequency under simulated burst load (24 groups, high message rate).

### 0.6 Repo hygiene
- Add `.gitignore` (`.env`, `.venv/`, `__pycache__/`, `*.pyc`, `*.session`, `*.session-journal`, `data/*.db`, `data/*.db-*`, `data/backup/`)
- Add `.env.example` with placeholder values
- Fix or remove `migrate_db.py` (contains hard-coded path `c:\Users\vivek\Desktop\TELEGRAM` from a different machine)
- Basic test suite: prioritize DB migrations, date filters, keyword matching thresholds, export annotation, reconnect/backfill logic

---

## Phase 1 — Entity Extraction (highest leverage, build this next)

### 1.1 Entity extraction pipeline
Extract structured entities from every message on ingest:
- Crypto wallet addresses: BTC, ETH, TRON/TRC-20, TON — regex pattern match + checksum validation where applicable
- UPI IDs
- Phone numbers (India-format aware)
- Email addresses
- Telegram handles (@mentions)
- URLs
- IBANs

Store in a new normalized `entities` table linked to `messages` (many-to-many: one message can contain multiple entities; one entity — e.g. a wallet address — can appear across many messages/groups).

**Schema sketch:**
```
entities: id, entity_type, entity_value, first_seen_at, last_seen_at
message_entities: message_id, entity_id, position_in_text
```

### 1.2 Wallet enrichment
- Query extracted wallet addresses against a chain explorer API (Etherscan for ETH, TronGrid for TRON, Blockchair as multi-chain fallback) for balance, first/last activity, total transaction volume.
- Flag wallets matching the OFAC SDN crypto address list (free, publicly available) — sanctioned-wallet hits are high-value flags for investigators.
- Cluster addresses that co-occur in the same message or campaign (same scam post posting multiple wallets = likely same operator).

---

## Phase 2 — Semantic Matching Layer

### 2.1 Embedding-based semantic search
Fuzzy string matching misses paraphrased/coded scam language ("double your money" won't match "investment scam" keyword literally). Encode messages with a multilingual embedding model (e.g. `bge-m3` or `paraphrase-multilingual-MiniLM`, consistent with the MiniLM already used elsewhere in your stack) and store vectors in a lightweight vector index (FAISS is sufficient at current scale; Qdrant if this grows past single-node).

### 2.2 Near-duplicate campaign clustering
Cluster message embeddings to detect the same scam text reposted with small variations across channels. Surface these as a single "campaign" entry in the dashboard instead of N individual message rows — this is the difference between an analyst seeing 400 noisy rows and seeing 1 coordinated campaign with 400 instances.

### 2.3 Message classification
Tag each message with a category (scam / recruitment / money-laundering / drug-sale / benign) using a lightweight classifier or zero-shot LLM call. Store as a column on `messages` or a separate `classifications` table if you want to preserve confidence scores/history.

---

## Phase 3 — Network & Behavioral Intelligence

### 3.1 Forward/actor graph
You already detect cross-group forwards in `exporter.py` — extend this into an actual graph structure (NetworkX is sufficient at this scale; skip Neo4j until multi-user/production scale justifies it). Nodes = senders/channels/wallets/handles. Edges = forwards, mentions, shared wallets.

### 3.2 Graph analytics
Run centrality/community detection (PageRank, Louvain) on the graph to surface high-influence channels and bridge accounts connecting otherwise-separate clusters.

### 3.3 Interactive graph explorer in dashboard
Frontend visualization using Cytoscape.js or Sigma.js so analysts can explore the network directly rather than reading exported edge lists.

### 3.4 Temporal/behavioral analytics
- Posting cadence per channel/actor
- Timezone inference from activity heatmaps (can help narrow operator location)
- Burst detection (change-point/z-score) to catch coordinated launch times across channels
- Actor lifecycle tracking (creation → rename → deletion events, where Telethon exposes this)

---

## Phase 4 — Multimodal Ingestion

Currently text-only. Add:
- Image/document download + OCR (Tesseract or PaddleOCR) — catches screenshotted wallet addresses and QR codes, a common scam-post pattern
- Perceptual hashing (pHash) on images to detect reused scam graphics across channels even when re-encoded/cropped
- QR code decode (often contains wallet/payment links directly)
- Optional: audio transcription (Whisper) for voice notes, if volume justifies it

---

## Phase 5 — Threat Scoring & Alerting

### 5.1 Composite risk score
Per message/sender score combining: keyword density, sanctioned-wallet presence, campaign membership, forward reach, new-account heuristics, urgency/pressure language markers.

### 5.2 Rolling sender scores
Persist per-sender scores over time so a channel/actor "heats up" as more signals accumulate, rather than scoring being a single-message snapshot.

### 5.3 Real-time alerting
Webhook/Telegram-bot/email push when a score crosses a defined threshold, instead of relying on someone actively checking the dashboard.

---

## Phase 6 — Analyst UX & Reporting

- Auto-generated PDF intelligence briefs (campaign summary, top actors, wallet exposure, network diagram)
- Saved queries and watchlists
- Case management — group related findings (shared wallet, shared phone, shared sender across groups) into a single investigation object, similar in spirit to the CaseSession pattern already used elsewhere
- STIX 2.1 / MISP export — only worth doing once this needs to plug into a larger institutional threat-intel workflow; not a near-term priority for a single-operator tool

---

## Phase 7 — Platform Hardening (only once scale/user-count justifies it)

Do **not** front-load this phase. These are correct long-term moves but solve problems you don't have yet at ~3,500 messages on SQLite:

- Postgres + TimescaleDB migration (keep SQLite for current scale; revisit if concurrent writers or message volume becomes a real bottleneck)
- Auth on the Flask dashboard (currently open on `:5000` — do this before any second person touches it or it leaves localhost, but doesn't need full OIDC/SSO yet)
- Field-level encryption for phone numbers/sender PII, configurable retention/redaction policy
- Chain-of-custody / hash-chained audit log of every ingested item — relevant once output is used as evidence, not before
- Dockerization (docker-compose for ingest/worker/api/vectordb) — useful for portability, not urgent
- Prometheus + Grafana observability (messages/sec, queue depth, reconnect count, match rate)
- Kubernetes/Helm, full RBAC — defer until this is a multi-user institutional deployment, not a personal/demo project

---

## Suggested Build Order Summary

1. Phase 0 — bug fixes (listener leak, batching, worker pool) — **do this before anything else**
2. Phase 1 — entity extraction + wallet enrichment
3. Phase 2 — embeddings + campaign clustering
4. Phase 3.1–3.2 — forward graph + analytics (skip graph DB, use NetworkX)
5. Phase 4 — OCR/image handling
6. Phase 5 — threat scoring + alerting
7. Phase 6 — reporting/case management
8. Phase 7 — only if/when this moves to multi-user or production deployment

Rationale: fixing ingestion correctness first prevents every downstream feature from computing expensive analysis (embeddings, graph, scoring) on duplicated or corrupted data. Entity extraction and semantic matching are the highest analyst-value features per unit of engineering effort and build directly on capabilities already used elsewhere in this project's ecosystem (MiniLM embeddings, crypto-domain knowledge). Heavy infrastructure (Neo4j, Kubernetes, RBAC/SSO, STIX export) is deferred until real multi-user scale demands it — building it now would be solving problems that don't exist yet at the cost of the fixes and features that do.
