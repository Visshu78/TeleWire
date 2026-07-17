"""
src/storage/database.py
-------------------------------------------------------------
SQLite persistence layer.
  - WAL journal mode       -> reads never block writes
  - PRAGMA synchronous=NORMAL -> safe + fast under WAL
  - check_same_thread=False   -> Flask + asyncio thread share safely
  - Row-factory returns dict-like sqlite3.Row objects

Schema additions vs v1:
  - messages.forward_from_name / forward_from_id  (fwd_from ground-truth)
  - groups.last_message_at                        (gap-backfill anchor)
  - pipeline_events table                         (disconnect / reconnect log)
-------------------------------------------------------------
"""

import os
import json
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/telegram_intel.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS messages (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id        INTEGER NOT NULL,
    group_name        TEXT,
    group_id          INTEGER,
    sender_name       TEXT,
    sender_phone      TEXT,
    sender_id         TEXT,
    text              TEXT,
    language          TEXT    DEFAULT 'unknown',
    is_forwarded      INTEGER DEFAULT 0,
    forward_from_name TEXT,
    forward_from_id   INTEGER,
    matched_keyword   TEXT,
    fuzzy_score       REAL    DEFAULT 0.0,
    is_matched        INTEGER DEFAULT 0,
    timestamp         TEXT    NOT NULL,
    hash              TEXT    UNIQUE NOT NULL,
    campaign_id       TEXT,
    threat_category   TEXT,
    media_path        TEXT,
    ocr_text          TEXT,
    phash             TEXT,
    qr_codes          TEXT,
    risk_score        REAL    DEFAULT 0.0,
    fetched_by        TEXT
);

CREATE TABLE IF NOT EXISTS groups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        INTEGER UNIQUE NOT NULL,
    group_name      TEXT,
    group_type      TEXT    DEFAULT 'group',
    is_active       INTEGER DEFAULT 1,
    member_count    INTEGER DEFAULT 0,
    last_message_at TEXT,
    last_message_id INTEGER,
    added_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS keywords (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword  TEXT UNIQUE NOT NULL COLLATE NOCASE,
    source   TEXT DEFAULT 'manual',
    added_at TEXT NOT NULL
);

-- Pipeline health events (disconnect / reconnect / backfill)
CREATE TABLE IF NOT EXISTS pipeline_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type       TEXT    NOT NULL,
    started_at       TEXT    NOT NULL,
    ended_at         TEXT,
    duration_seconds REAL,
    details          TEXT
);

CREATE INDEX IF NOT EXISTS idx_msg_timestamp    ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_msg_group_id     ON messages(group_id);
CREATE INDEX IF NOT EXISTS idx_msg_keyword      ON messages(matched_keyword);
CREATE INDEX IF NOT EXISTS idx_msg_matched      ON messages(is_matched);
CREATE INDEX IF NOT EXISTS idx_msg_language     ON messages(language);
CREATE INDEX IF NOT EXISTS idx_msg_fwd_id       ON messages(forward_from_id);
CREATE INDEX IF NOT EXISTS idx_evt_type_started ON pipeline_events(event_type, started_at);

-- Phase 1 Entity tables
CREATE TABLE IF NOT EXISTS entities (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type    TEXT NOT NULL,
    entity_value   TEXT NOT NULL,
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL,
    UNIQUE(entity_type, entity_value)
);

CREATE TABLE IF NOT EXISTS message_entities (
    message_id       INTEGER NOT NULL,
    entity_id        INTEGER NOT NULL,
    position_in_text INTEGER,
    PRIMARY KEY(message_id, entity_id),
    FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS wallet_enrichments (
    entity_id        INTEGER PRIMARY KEY,
    balance          REAL DEFAULT 0.0,
    tx_count         INTEGER DEFAULT 0,
    total_volume     REAL DEFAULT 0.0,
    first_active     TEXT,
    last_active      TEXT,
    is_sanctioned    INTEGER DEFAULT 0,
    enrichment_source TEXT,
    last_enriched_at TEXT,
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS phone_enrichments (
    entity_id        INTEGER PRIMARY KEY,
    country_code     TEXT,
    country_name     TEXT,
    location         TEXT,
    carrier          TEXT,
    national_number  TEXT,
    is_valid         INTEGER DEFAULT 1,
    last_enriched_at TEXT,
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS geocodes (
    entity_id   INTEGER PRIMARY KEY,
    latitude    REAL NOT NULL,
    longitude   REAL NOT NULL,
    country     TEXT,
    city        TEXT,
    resolved_at TEXT NOT NULL,
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_entities_value ON entities(entity_value);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

CREATE TABLE IF NOT EXISTS campaigns (
    id                  TEXT PRIMARY KEY,
    campaign_name       TEXT NOT NULL,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    threat_category     TEXT NOT NULL,
    representative_text TEXT
);

CREATE TABLE IF NOT EXISTS sender_profiles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id           TEXT UNIQUE NOT NULL,
    sender_phone        TEXT,
    total_messages      INTEGER DEFAULT 0,
    cumulative_risk     REAL DEFAULT 0.0,
    average_risk        REAL DEFAULT 0.0,
    last_seen_at        TEXT,
    risk_tier           TEXT DEFAULT 'Low'
);

CREATE INDEX IF NOT EXISTS idx_sender_cum_risk ON sender_profiles(cumulative_risk);

CREATE TABLE IF NOT EXISTS cases (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    description         TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id             TEXT NOT NULL,
    item_type           TEXT NOT NULL, -- 'message', 'wallet', 'actor'
    item_value          TEXT NOT NULL,
    added_at            TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS watchlists (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    query_params        TEXT NOT NULL, -- JSON string of filters
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telegram_accounts (
    phone           TEXT PRIMARY KEY,
    api_id          INTEGER NOT NULL,
    api_hash        TEXT NOT NULL,
    session_name    TEXT UNIQUE NOT NULL,
    is_active       INTEGER DEFAULT 1,
    status          TEXT DEFAULT 'disconnected'
);

CREATE INDEX IF NOT EXISTS idx_case_items_case_id ON case_items(case_id);

CREATE TABLE IF NOT EXISTS pending_groups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        INTEGER,
    group_name      TEXT,
    group_username  TEXT,
    member_count    INTEGER DEFAULT 0,
    invite_link     TEXT,
    source          TEXT NOT NULL,
    source_keyword  TEXT,
    discovered_at   TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    context_text    TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_grp_unique
    ON pending_groups(group_id, group_name, invite_link);
"""

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Create all tables + indexes and enable WAL. Safe to call on every startup.
    Also applies additive column migrations so existing databases are upgraded
    without data loss.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.execute("PRAGMA wal_autocheckpoint=1000")
        conn.executescript(_DDL)
        # Additive migrations -- ALTER TABLE IF NOT EXISTS isn't supported,
        # so we check PRAGMA table_info and add only missing columns.
        _migrate(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info("Database ready at %s", db_path)


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply additive schema changes to existing databases."""
    msg_cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
    grp_cols = {r[1] for r in conn.execute("PRAGMA table_info(groups)").fetchall()}

    migrations = []
    if "forward_from_name" not in msg_cols:
        migrations.append("ALTER TABLE messages ADD COLUMN forward_from_name TEXT")
    if "forward_from_id" not in msg_cols:
        migrations.append("ALTER TABLE messages ADD COLUMN forward_from_id INTEGER")
    if "last_message_at" not in grp_cols:
        migrations.append("ALTER TABLE groups ADD COLUMN last_message_at TEXT")
    if "last_message_id" not in grp_cols:
        migrations.append("ALTER TABLE groups ADD COLUMN last_message_id INTEGER")
    if "campaign_id" not in msg_cols:
        migrations.append("ALTER TABLE messages ADD COLUMN campaign_id TEXT")
    if "threat_category" not in msg_cols:
        migrations.append("ALTER TABLE messages ADD COLUMN threat_category TEXT")
    if "media_path" not in msg_cols:
        migrations.append("ALTER TABLE messages ADD COLUMN media_path TEXT")
    if "ocr_text" not in msg_cols:
        migrations.append("ALTER TABLE messages ADD COLUMN ocr_text TEXT")
    if "phash" not in msg_cols:
        migrations.append("ALTER TABLE messages ADD COLUMN phash TEXT")
    if "qr_codes" not in msg_cols:
        migrations.append("ALTER TABLE messages ADD COLUMN qr_codes TEXT")
    if "risk_score" not in msg_cols:
        migrations.append("ALTER TABLE messages ADD COLUMN risk_score REAL DEFAULT 0.0")
    if "fetched_by" not in msg_cols:
        migrations.append("ALTER TABLE messages ADD COLUMN fetched_by TEXT")

    for sql in migrations:
        try:
            conn.execute(sql)
            logger.info("DB migration: %s", sql)
        except Exception as exc:
            logger.warning("Migration skipped (%s): %s", sql, exc)

    # Ensure sender_profiles and new indices exist on legacy databases
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sender_profiles (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id           TEXT UNIQUE NOT NULL,
                sender_phone        TEXT,
                total_messages      INTEGER DEFAULT 0,
                cumulative_risk     REAL DEFAULT 0.0,
                average_risk        REAL DEFAULT 0.0,
                last_seen_at        TEXT,
                risk_tier           TEXT DEFAULT 'Low'
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sender_cum_risk ON sender_profiles(cumulative_risk);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_campaign_id ON messages(campaign_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_threat_cat ON messages(threat_category);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_phash ON messages(phash);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_risk_score ON messages(risk_score);")
        
        # Phase 6 tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id                  TEXT PRIMARY KEY,
                title               TEXT NOT NULL,
                description         TEXT,
                created_at          TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS case_items (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id             TEXT NOT NULL,
                item_type           TEXT NOT NULL,
                item_value          TEXT NOT NULL,
                added_at            TEXT NOT NULL,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlists (
                id                  TEXT PRIMARY KEY,
                name                TEXT NOT NULL,
                query_params        TEXT NOT NULL,
                created_at          TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_case_items_case_id ON case_items(case_id);")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telegram_accounts (
                phone           TEXT PRIMARY KEY,
                api_id          INTEGER NOT NULL,
                api_hash        TEXT NOT NULL,
                session_name    TEXT UNIQUE NOT NULL,
                is_active       INTEGER DEFAULT 1,
                status          TEXT DEFAULT 'disconnected'
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_groups (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id        INTEGER,
                group_name      TEXT,
                group_username  TEXT,
                member_count    INTEGER DEFAULT 0,
                invite_link     TEXT,
                source          TEXT NOT NULL,
                source_keyword  TEXT,
                discovered_at   TEXT NOT NULL,
                status          TEXT DEFAULT 'pending',
                context_text    TEXT
            );
        """)
        # Migrate existing pending_groups table if context_text column missing
        try:
            pg_cols = {r[1] for r in conn.execute("PRAGMA table_info(pending_groups)").fetchall()}
            if "context_text" not in pg_cols:
                conn.execute("ALTER TABLE pending_groups ADD COLUMN context_text TEXT")
                logger.info("DB migration: added context_text to pending_groups")
        except Exception as _e:
            pass

        # Create phone_enrichments table if missing
        conn.execute("""
            CREATE TABLE IF NOT EXISTS phone_enrichments (
                entity_id        INTEGER PRIMARY KEY,
                country_code     TEXT,
                country_name     TEXT,
                location         TEXT,
                carrier          TEXT,
                national_number  TEXT,
                is_valid         INTEGER DEFAULT 1,
                last_enriched_at TEXT,
                FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
            );
        """)

        # Create settings table if missing
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)

        # Create geocodes table if missing
        conn.execute("""
            CREATE TABLE IF NOT EXISTS geocodes (
                entity_id   INTEGER PRIMARY KEY,
                latitude    REAL NOT NULL,
                longitude   REAL NOT NULL,
                country     TEXT,
                city        TEXT,
                resolved_at TEXT NOT NULL,
                FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
            );
        """)

        # Create leak_registry table if missing
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leak_registry (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_value TEXT UNIQUE NOT NULL,
                source_leak  TEXT NOT NULL,
                leak_date    TEXT NOT NULL,
                details      TEXT
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leak_entity_value ON leak_registry(entity_value);")

        # Seed mock leak registry values if empty
        row_count = conn.execute("SELECT COUNT(*) FROM leak_registry").fetchone()[0]
        if row_count == 0:
            mock_leaks = [
                ("@alice_tg", "RaidForums Cybercrime Breach", "2021-08-12", "Linked to active forum selling carding templates and compromised banking logins."),
                ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "Silk Road FBI List & Crypto Leaks", "2020-11-04", "Genesis transaction address flagged in historic cybercrime and underground darknet marketplace forums."),
                ("+919999999999", "Telegram BOT Scraper Leak DB", "2023-05-18", "Compromised phone registry exposed via threat actor scanning bot lookup tools."),
                ("@fraudster_tg", "Underground Hackers Telegram Channel Dump", "2025-02-10", "Linked to financial scams and active identity theft campaigns.")
            ]
            conn.executemany(
                "INSERT INTO leak_registry (entity_value, source_leak, leak_date, details) VALUES (?, ?, ?, ?)",
                mock_leaks
            )
            logger.info("Seeded %d leak registry records", len(mock_leaks))
    except Exception as exc:
        logger.error("Failed to execute phase 5 / 6 migrations: %s", exc)


@contextmanager
def get_db(db_path: str = DEFAULT_DB_PATH):
    """
    Thread-safe context manager: WAL + row_factory, commit on success,
    rollback on exception, always closes.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# High-level handler
# ---------------------------------------------------------------------------

class DatabaseHandler:
    """All DB operations the pipeline needs, in one place."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path

    # ── Messages ──────────────────────────────────────────────────────────────

    def insert_message(self, data: dict) -> bool:
        """
        Insert a message row. INSERT OR IGNORE silently skips duplicate hashes.
        Also bumps groups.last_message_at so the gap-backfill anchor stays fresh.
        Returns True if a new row was inserted.
        """
        sql = """
            INSERT OR IGNORE INTO messages
                (message_id, group_id, group_name, sender_name, sender_phone, sender_id,
                 text, language, is_forwarded, forward_from_name, forward_from_id,
                 matched_keyword, fuzzy_score, is_matched, timestamp, hash,
                 campaign_id, threat_category, media_path, ocr_text, phash, qr_codes, risk_score, fetched_by)
            VALUES
                (:message_id, :group_id, :group_name, :sender_name, :sender_phone, :sender_id,
                 :text, :language, :is_forwarded, :forward_from_name, :forward_from_id,
                 :matched_keyword, :fuzzy_score, :is_matched, :timestamp, :hash,
                 :campaign_id, :threat_category, :media_path, :ocr_text, :phash, :qr_codes, :risk_score, :fetched_by)
        """
        try:
            self._fill_msg_defaults(data)
            with get_db(self.db_path) as conn:
                cur = conn.execute(sql, data)
                inserted = cur.rowcount == 1
                if inserted:
                    # Keep last_message_at and last_message_id current so watchdog knows where to backfill from
                    conn.execute(
                        "UPDATE groups SET last_message_at=?, last_message_id=MAX(COALESCE(last_message_id, 0), ?) WHERE group_id=?",
                        (data["timestamp"], data["message_id"], data["group_id"]),
                    )
            return inserted
        except Exception as exc:
            logger.error("insert_message failed: %s", exc)
            return False

    def _fill_msg_defaults(self, data: dict) -> None:
        """Fill all database-bindable columns with safe defaults to prevent sqlite binding errors."""
        data.setdefault("message_id", None)
        data.setdefault("group_id", None)
        data.setdefault("group_name", None)
        data.setdefault("sender_name", None)
        data.setdefault("sender_phone", None)
        data.setdefault("sender_id", None)
        data.setdefault("text", None)
        data.setdefault("language", None)
        data.setdefault("is_forwarded", 0)
        data.setdefault("forward_from_name", None)
        data.setdefault("forward_from_id", None)
        data.setdefault("matched_keyword", None)
        data.setdefault("fuzzy_score", 0.0)
        data.setdefault("is_matched", 0)
        data.setdefault("timestamp", None)
        data.setdefault("hash", None)
        data.setdefault("campaign_id", None)
        data.setdefault("threat_category", None)
        data.setdefault("media_path", None)
        data.setdefault("ocr_text", None)
        data.setdefault("phash", None)
        data.setdefault("qr_codes", None)
        data.setdefault("risk_score", 0.0)
        data.setdefault("fetched_by", None)
        if isinstance(data.get("qr_codes"), list):
            data["qr_codes"] = json.dumps(data["qr_codes"])

    def insert_messages_batch(self, batch_data: list) -> int:
        """
        Insert a batch of messages inside a single transaction.
        Also updates groups.last_message_at / last_message_id for the groups.
        Returns the number of messages successfully inserted.
        """
        if not batch_data:
            return 0

        sql = """
            INSERT OR IGNORE INTO messages
                (message_id, group_id, group_name, sender_name, sender_phone, sender_id,
                 text, language, is_forwarded, forward_from_name, forward_from_id,
                 matched_keyword, fuzzy_score, is_matched, timestamp, hash,
                 campaign_id, threat_category, media_path, ocr_text, phash, qr_codes, risk_score, fetched_by)
            VALUES
                (:message_id, :group_id, :group_name, :sender_name, :sender_phone, :sender_id,
                 :text, :language, :is_forwarded, :forward_from_name, :forward_from_id,
                 :matched_keyword, :fuzzy_score, :is_matched, :timestamp, :hash,
                 :campaign_id, :threat_category, :media_path, :ocr_text, :phash, :qr_codes, :risk_score, :fetched_by)
        """
        
        # Aggregate the maximum message_id and timestamp for each group in the batch
        group_updates = {}
        for msg in batch_data:
            self._fill_msg_defaults(msg)
            g_id = msg["group_id"]
            ts = msg["timestamp"]
            m_id = msg["message_id"]
            if g_id not in group_updates:
                group_updates[g_id] = {"timestamp": ts, "message_id": m_id}
            else:
                if ts > group_updates[g_id]["timestamp"]:
                    group_updates[g_id]["timestamp"] = ts
                if m_id > group_updates[g_id]["message_id"]:
                    group_updates[g_id]["message_id"] = m_id

        inserted_count = 0
        try:
            with get_db(self.db_path) as conn:
                cur = conn.executemany(sql, batch_data)
                inserted_count = cur.rowcount if cur.rowcount >= 0 else len(batch_data)
                
                # Update groups
                for g_id, update_info in group_updates.items():
                    conn.execute(
                        "UPDATE groups SET last_message_at=?, last_message_id=MAX(COALESCE(last_message_id, 0), ?) WHERE group_id=?",
                        (update_info["timestamp"], update_info["message_id"], g_id),
                    )
            return inserted_count
        except Exception as exc:
            logger.error("insert_messages_batch failed: %s", exc)
            return 0

    def get_last_seen_ts(self, group_id: int) -> Optional[str]:
        """Return the ISO-8601 timestamp of the last stored message for this group."""
        with get_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT last_message_at FROM groups WHERE group_id=?", (group_id,)
            ).fetchone()
        return row["last_message_at"] if row else None

    def get_messages(
        self,
        keyword: Optional[str] = None,
        group_id: Optional[int] = None,
        datetime_from: Optional[str] = None,   # full ISO-8601 string (date or datetime)
        datetime_to: Optional[str] = None,     # full ISO-8601 string (date or datetime)
        matched_only: bool = False,
        page: int = 1,
        page_size: int = 50,
        sender_name: Optional[str] = None,
        fetched_by: Optional[str] = None,
        request_dow: Optional[int] = None,
        request_hour: Optional[int] = None,
        q: Optional[str] = None,
    ) -> dict:
        """Paginated + filtered message list. Accepts full datetime strings."""
        if datetime_from and datetime_to and datetime_from > datetime_to:
            datetime_from, datetime_to = datetime_to, datetime_from

        clauses, params = [], []
        if keyword:
            if isinstance(keyword, list):
                if keyword:
                    placeholders = ",".join("?" for _ in keyword)
                    clauses.append(f"matched_keyword IN ({placeholders})")
                    params.extend(keyword)
            else:
                clauses.append("matched_keyword = ?")
                params.append(keyword)
        if group_id:
            if isinstance(group_id, list):
                if group_id:
                    placeholders = ",".join("?" for _ in group_id)
                    clauses.append(f"group_id IN ({placeholders})")
                    params.extend(group_id)
            else:
                clauses.append("group_id = ?")
                params.append(group_id)
        if datetime_from:
            clauses.append("timestamp >= ?")
            params.append(_normalise_dt(datetime_from, end=False))
        if datetime_to:
            clauses.append("timestamp <= ?")
            params.append(_normalise_dt(datetime_to, end=True))
        if matched_only:
            clauses.append("is_matched = 1")
        if sender_name:
            clauses.append("sender_name = ?")
            params.append(sender_name)
        if fetched_by:
            clauses.append("fetched_by = ?")
            params.append(fetched_by)
        if q:
            clauses.append("""
                (text LIKE ? OR ocr_text LIKE ? OR sender_name LIKE ? OR sender_id = ? OR 
                 id IN (SELECT message_id FROM message_entities me JOIN entities e ON me.entity_id = e.id WHERE e.entity_value = ?))
            """)
            q_like = f"%{q.strip()}%"
            params.extend([q_like, q_like, q_like, q.strip(), q.strip()])
        if request_dow is not None:
            # Map client DOW (0=Mon...6=Sun) back to SQLite %w (0=Sun...6=Sat)
            sqlite_dow = (int(request_dow) + 1) % 7
            clauses.append("CAST(strftime('%w', timestamp) AS INTEGER) = ?")

            params.append(sqlite_dow)
        if request_hour is not None:
            clauses.append("CAST(strftime('%H', timestamp) AS INTEGER) = ?")
            params.append(int(request_hour))


        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        offset = (page - 1) * page_size

        with get_db(self.db_path) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM messages {where}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM messages {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "messages": [dict(r) for r in rows],
        }

    def get_stats(
        self,
        datetime_from: Optional[str] = None,
        datetime_to: Optional[str] = None,
        fetched_by: Optional[str] = None,
    ) -> dict:
        """Aggregate counts for dashboard stat cards + charts."""
        if datetime_from and datetime_to and datetime_from > datetime_to:
            datetime_from, datetime_to = datetime_to, datetime_from

        clauses, params = [], []
        if datetime_from:
            clauses.append("timestamp >= ?")
            params.append(_normalise_dt(datetime_from, end=False))
        if datetime_to:
            clauses.append("timestamp <= ?")
            params.append(_normalise_dt(datetime_to, end=True))
        if fetched_by:
            clauses.append("fetched_by = ?")
            params.append(fetched_by)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        and_clause = ("AND " + " AND ".join(clauses)) if clauses else ""

        with get_db(self.db_path) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM messages {where}", params
            ).fetchone()[0]

            matched = conn.execute(
                f"SELECT COUNT(*) FROM messages WHERE is_matched=1 {and_clause}", params
            ).fetchone()[0]

            per_keyword = conn.execute(
                f"""SELECT matched_keyword, COUNT(*) AS cnt
                    FROM messages WHERE is_matched=1 {and_clause}
                    GROUP BY matched_keyword ORDER BY cnt DESC LIMIT 20""",
                params,
            ).fetchall()

            per_group = conn.execute(
                f"""SELECT group_name, COUNT(*) AS cnt
                    FROM messages {where}
                    GROUP BY group_name ORDER BY cnt DESC LIMIT 20""",
                params,
            ).fetchall()

            per_day = conn.execute(
                f"""SELECT substr(timestamp, 1, 10) AS day, COUNT(*) AS cnt
                    FROM messages {where}
                    GROUP BY day ORDER BY day DESC LIMIT 30""",
                params,
            ).fetchall()

        return {
            "total": total,
            "matched": matched,
            "per_keyword": [dict(r) for r in per_keyword],
            "per_group":   [dict(r) for r in per_group],
            "per_day":     [dict(r) for r in per_day],
        }

    def get_all_hashes(self) -> set:
        with get_db(self.db_path) as conn:
            rows = conn.execute("SELECT hash FROM messages").fetchall()
        return {r["hash"] for r in rows}

    def get_recent_unmatched_messages(self, limit: int = 1000) -> list:
        """Fetch recent unmatched messages for retroactive evaluation."""
        with get_db(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE is_matched=0 ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def update_message_match(self, row_id: int, matched_keyword: str, fuzzy_score: float) -> None:
        """Update a message's match status retroactively."""
        with get_db(self.db_path) as conn:
            conn.execute(
                "UPDATE messages SET matched_keyword=?, fuzzy_score=?, is_matched=1 WHERE id=?",
                (matched_keyword, fuzzy_score, row_id)
            )

    # ── Groups ────────────────────────────────────────────────────────────────

    def upsert_group(
        self,
        group_id: int,
        group_name: str,
        group_type: str = "group",
        member_count: int = 0,
    ) -> None:
        sql = """
            INSERT INTO groups (group_id, group_name, group_type, member_count, is_active, added_at)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                group_name   = excluded.group_name,
                member_count = excluded.member_count
        """
        with get_db(self.db_path) as conn:
            conn.execute(
                sql,
                (group_id, group_name, group_type, member_count,
                 datetime.now(timezone.utc).isoformat()),
            )

    def toggle_group(self, group_id: int) -> bool:
        with get_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT is_active FROM groups WHERE group_id=?", (group_id,)
            ).fetchone()
            if row is None:
                return False
            new_state = 0 if row["is_active"] else 1
            conn.execute(
                "UPDATE groups SET is_active=? WHERE group_id=?", (new_state, group_id)
            )
        return bool(new_state)

    def get_all_groups(self) -> list:
        with get_db(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM groups ORDER BY group_name").fetchall()
        return [dict(r) for r in rows]

    def get_active_group_ids(self) -> list:
        with get_db(self.db_path) as conn:
            rows = conn.execute(
                "SELECT group_id FROM groups WHERE is_active=1"
            ).fetchall()
        return [r["group_id"] for r in rows]

    def get_active_groups(self) -> list:
        """Return full group rows for active groups (needed by gap backfill)."""
        with get_db(self.db_path) as conn:
            rows = conn.execute(
                "SELECT group_id, group_name, last_message_at, last_message_id FROM groups WHERE is_active=1"
            ).fetchall()
        return [dict(r) for r in rows]

    def remove_group(self, group_id: int) -> bool:
        """
        Mark a group as inactive (is_active=0) so the pipeline stops
        monitoring it. Returns True if a row was updated, False if not found.
        We keep the row (and all messages) for historical analysis.
        """
        try:
            with get_db(self.db_path) as conn:
                cur = conn.execute(
                    "UPDATE groups SET is_active = 0 WHERE group_id = ?",
                    (group_id,),
                )
            return cur.rowcount > 0
        except Exception as exc:
            logger.error("remove_group failed: %s", exc)
            return False

    # ── Keywords ──────────────────────────────────────────────────────────────

    def get_keywords(self) -> list:
        with get_db(self.db_path) as conn:
            rows = conn.execute("SELECT keyword FROM keywords ORDER BY keyword").fetchall()
        return [r["keyword"] for r in rows]

    def add_keyword(self, keyword: str, source: str = "manual") -> bool:
        kw = keyword.strip().lower()
        if not kw:
            return False
        try:
            with get_db(self.db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO keywords (keyword, source, added_at) VALUES (?,?,?)",
                    (kw, source, datetime.now(timezone.utc).isoformat()),
                )
            return True
        except Exception as exc:
            logger.error("add_keyword failed: %s", exc)
            return False

    def delete_keyword(self, keyword: str) -> bool:
        try:
            with get_db(self.db_path) as conn:
                conn.execute("DELETE FROM keywords WHERE keyword=?", (keyword.lower(),))
            return True
        except Exception as exc:
            logger.error("delete_keyword failed: %s", exc)
            return False

    def seed_keywords_from_file(self, filepath: str) -> int:
        count = 0
        try:
            with open(filepath, encoding="utf-8") as fh:
                for line in fh:
                    kw = line.strip()
                    if kw and not kw.startswith("#"):
                        if self.add_keyword(kw, source="file"):
                            count += 1
        except FileNotFoundError:
            logger.warning("keywords file not found: %s", filepath)
        return count

    # ── Pipeline events ───────────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        started_at: str,
        ended_at: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        details: Optional[str] = None,
    ) -> int:
        """
        Insert a pipeline event row. Returns the new row id.
        event_type examples: 'disconnect', 'reconnect', 'backfill', 'startup'.
        """
        with get_db(self.db_path) as conn:
            cur = conn.execute(
                """INSERT INTO pipeline_events
                   (event_type, started_at, ended_at, duration_seconds, details)
                   VALUES (?, ?, ?, ?, ?)""",
                (event_type, started_at, ended_at, duration_seconds, details),
            )
            return cur.lastrowid

    def close_event(
        self,
        event_id: int,
        ended_at: str,
        duration_seconds: float,
        details: Optional[str] = None,
    ) -> None:
        with get_db(self.db_path) as conn:
            conn.execute(
                """UPDATE pipeline_events
                   SET ended_at=?, duration_seconds=?, details=COALESCE(?, details)
                   WHERE id=?""",
                (ended_at, duration_seconds, details, event_id),
            )

    def get_pipeline_health(self, days: int = 1) -> dict:
        """Return disconnect stats for the last N days."""
        cutoff = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}T00:00:00"
        with get_db(self.db_path) as conn:
            rows = conn.execute(
                """SELECT event_type, started_at, ended_at, duration_seconds, details
                   FROM pipeline_events
                   WHERE started_at >= ?
                   ORDER BY started_at DESC""",
                (cutoff,),
            ).fetchall()

        events = [dict(r) for r in rows]
        disconnects = [e for e in events if e["event_type"] == "disconnect"]
        total_down = sum(
            (e["duration_seconds"] or 0) for e in disconnects
        )
        return {
            "events": events,
            "disconnect_count_today": len(disconnects),
            "total_downtime_seconds_today": round(total_down, 1),
        }

    # ── Phase 1 Entity Methods ────────────────────────────────────────────────
    
    def save_message_entities(self, message_row_id: int, entities_list: list, msg_timestamp: str) -> list:
        """
        Save entities found in a message and link them in message_entities.
        Returns a list of saved crypto entities that need background enrichment.
        """
        crypto_to_enrich = []
        if not entities_list:
            return crypto_to_enrich

        try:
            with get_db(self.db_path) as conn:
                for ent in entities_list:
                    etype = ent["type"]
                    evalue = ent["value"].strip()
                    pos = ent.get("position")
                    is_sanctioned = ent.get("is_sanctioned", 0)
                    
                    # Check if entity exists
                    row = conn.execute(
                        "SELECT id, last_seen_at FROM entities WHERE entity_type=? AND entity_value=?",
                        (etype, evalue)
                    ).fetchone()
                    
                    if row:
                        entity_id = row["id"]
                        last_seen = row["last_seen_at"]
                        if msg_timestamp > last_seen:
                            conn.execute(
                                "UPDATE entities SET last_seen_at=? WHERE id=?",
                                (msg_timestamp, entity_id)
                            )
                    else:
                        cur = conn.execute(
                            "INSERT INTO entities (entity_type, entity_value, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
                            (etype, evalue, msg_timestamp, msg_timestamp)
                        )
                        entity_id = cur.lastrowid
                    
                    # Link to message
                    conn.execute(
                        "INSERT OR IGNORE INTO message_entities (message_id, entity_id, position_in_text) VALUES (?, ?, ?)",
                        (message_row_id, entity_id, pos)
                    )
                    
                    if etype.startswith("crypto_"):
                        crypto_to_enrich.append({
                            "id": entity_id,
                            "value": evalue,
                            "type": etype,
                            "is_sanctioned": is_sanctioned
                        })
                    elif etype == "phone_number":
                        self._enrich_phone_number_conn(conn, entity_id, evalue)
            return crypto_to_enrich
        except Exception as exc:
            logger.error("save_message_entities failed: %s", exc)
            return []

    def get_message_ids_by_hashes(self, hashes: list) -> dict:
        """Return a mapping of hash -> database row_id for the given hashes."""
        if not hashes:
            return {}
        placeholders = ",".join(["?"] * len(hashes))
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(
                    f"SELECT id, hash FROM messages WHERE hash IN ({placeholders})",
                    hashes
                ).fetchall()
            return {r["hash"]: r["id"] for r in rows}
        except Exception as exc:
            logger.error("get_message_ids_by_hashes failed: %s", exc)
            return {}

    def upsert_wallet_enrichment(self, entity_id: int, data: dict) -> None:
        """Upsert wallet balance and tx volume info."""
        sql = """
            INSERT INTO wallet_enrichments (
                entity_id, balance, tx_count, total_volume,
                first_active, last_active, is_sanctioned,
                enrichment_source, last_enriched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                balance = excluded.balance,
                tx_count = excluded.tx_count,
                total_volume = excluded.total_volume,
                first_active = excluded.first_active,
                last_active = excluded.last_active,
                is_sanctioned = excluded.is_sanctioned,
                enrichment_source = excluded.enrichment_source,
                last_enriched_at = excluded.last_enriched_at
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            with get_db(self.db_path) as conn:
                conn.execute(
                    sql,
                    (entity_id, data.get("balance", 0.0), data.get("tx_count", 0),
                     data.get("total_volume", 0.0), data.get("first_active"),
                     data.get("last_active"), data.get("is_sanctioned", 0),
                     data.get("enrichment_source"), now)
                )
        except Exception as exc:
            logger.error("upsert_wallet_enrichment failed: %s", exc)

    def upsert_phone_enrichment(self, entity_id: int, data: dict) -> None:
        """Upsert phone country, location, carrier details."""
        sql = """
            INSERT INTO phone_enrichments (
                entity_id, country_code, country_name, location,
                carrier, national_number, is_valid, last_enriched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                country_code = excluded.country_code,
                country_name = excluded.country_name,
                location = excluded.location,
                carrier = excluded.carrier,
                national_number = excluded.national_number,
                is_valid = excluded.is_valid,
                last_enriched_at = excluded.last_enriched_at
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            with get_db(self.db_path) as conn:
                conn.execute(
                    sql,
                    (entity_id, data.get("country_code"), data.get("country_name"),
                     data.get("location"), data.get("carrier"), data.get("national_number"),
                     data.get("is_valid", 1), now)
                )
        except Exception as exc:
            logger.error("upsert_phone_enrichment failed: %s", exc)

    def get_phone_enrichment(self, entity_value: str) -> dict | None:
        """Retrieve phone enrichment details by number value."""
        sql = """
            SELECT p.*, e.entity_value, e.entity_type
            FROM phone_enrichments p
            JOIN entities e ON p.entity_id = e.id
            WHERE e.entity_value = ?
        """
        try:
            with get_db(self.db_path) as conn:
                row = conn.execute(sql, (entity_value.strip(),)).fetchone()
            return dict(row) if row else None
        except Exception as exc:
            logger.error("get_phone_enrichment failed: %s", exc)
            return None

    def _enrich_phone_number_obj(self, entity_id: int, number_str: str) -> None:
        """Perform offline lookup using phonenumbers package and save to DB."""
        try:
            with get_db(self.db_path) as conn:
                self._enrich_phone_number_conn(conn, entity_id, number_str)
        except Exception as exc:
            logger.warning("Failed to enrich phone number %s: %s", number_str, exc)

    def _enrich_phone_number_conn(self, conn: sqlite3.Connection, entity_id: int, number_str: str) -> None:
        """Perform offline lookup using phonenumbers package and save to DB using active connection."""
        try:
            import phonenumbers
            from phonenumbers import geocoder, carrier, phonenumberutil
            
            # Parse number. India is default region if missing '+' prefix
            parsed = phonenumbers.parse(number_str, "IN")
            is_valid = 1 if phonenumbers.is_valid_number(parsed) else 0
            
            country_code = str(parsed.country_code) if parsed.country_code else None
            national_number = str(parsed.national_number) if parsed.national_number else None
            
            region_code = phonenumberutil.region_code_for_number(parsed)
            country_name = region_code
            
            location = geocoder.description_for_number(parsed, "en") or ""
            if location:
                country_name = location.split(",")[-1].strip()
                
            carrier_name = carrier.name_for_number(parsed, "en") or ""
            
            now = datetime.now(timezone.utc).isoformat()
            sql = """
                INSERT INTO phone_enrichments (
                    entity_id, country_code, country_name, location,
                    carrier, national_number, is_valid, last_enriched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    country_code = excluded.country_code,
                    country_name = excluded.country_name,
                    location = excluded.location,
                    carrier = excluded.carrier,
                    national_number = excluded.national_number,
                    is_valid = excluded.is_valid,
                    last_enriched_at = excluded.last_enriched_at
            """
            conn.execute(
                sql,
                (entity_id, country_code, country_name, location,
                 carrier_name, national_number, is_valid, now)
            )
        except Exception as exc:
            logger.warning("Failed to enrich phone number %s: %s", number_str, exc)


    def get_setting(self, key: str, default_val: str = None) -> str | None:
        """Fetch setting value from database."""
        try:
            with get_db(self.db_path) as conn:
                row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default_val
        except Exception as exc:
            logger.error("get_setting failed for key %s: %s", key, exc)
            return default_val

    def set_setting(self, key: str, value: str) -> None:
        """Save setting value to database."""
        try:
            with get_db(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value))
                )
        except Exception as exc:
            logger.error("set_setting failed for key %s: %s", key, exc)

    def get_entity_relationships(self, fetched_by: str = None) -> list:
        """
        Retrieve all mappings between message senders, groups, and extracted entities.
        Used to build coordinated entity threat maps.
        """
        sql = """
            SELECT e.id AS entity_id, e.entity_type, e.entity_value,
                   m.sender_name, m.sender_id, m.group_id, m.group_name
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            WHERE m.sender_name IS NOT NULL
        """
        params = []
        if fetched_by:
            sql += " AND m.fetched_by = ?"
            params.append(fetched_by)
            
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_entity_relationships failed: %s", exc)
            return []

    def get_actor_node_details(self, actor_key: str) -> dict:
        """
        Fetch summary metrics and linked indicators for a visual node actor.
        """
        actor_key = actor_key.strip()
        
        sql_metrics = """
            SELECT COUNT(*) as msg_count, MIN(timestamp) as first_seen, MAX(timestamp) as last_seen
            FROM messages
            WHERE sender_id = ? OR sender_name = ?
        """
        
        sql_groups = """
            SELECT DISTINCT group_id, group_name
            FROM messages
            WHERE (sender_id = ? OR sender_name = ?) AND group_name IS NOT NULL
            LIMIT 8
        """
        
        sql_entities = """
            SELECT DISTINCT e.entity_type, e.entity_value
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            WHERE m.sender_id = ? OR m.sender_name = ?
            LIMIT 12
        """
        
        details = {
            "msg_count": 0,
            "first_seen": None,
            "last_seen": None,
            "groups": [],
            "iocs": []
        }
        
        try:
            with get_db(self.db_path) as conn:
                m_row = conn.execute(sql_metrics, (actor_key, actor_key)).fetchone()
                if m_row and m_row["msg_count"] > 0:
                    details["msg_count"] = m_row["msg_count"]
                    details["first_seen"] = m_row["first_seen"]
                    details["last_seen"] = m_row["last_seen"]
                    
                g_rows = conn.execute(sql_groups, (actor_key, actor_key)).fetchall()
                details["groups"] = [dict(r) for r in g_rows]
                
                e_rows = conn.execute(sql_entities, (actor_key, actor_key)).fetchall()
                details["iocs"] = [dict(r) for r in e_rows]
        except Exception as exc:
            logger.error("get_actor_node_details failed for %s: %s", actor_key, exc)
            
        return details

    def get_entity_node_details(self, entity_id: int) -> dict:
        """
        Fetch summary metrics and linked actors/groups for a visual entity node.
        """
        sql_metrics = """
            SELECT COUNT(*) as msg_count, MIN(m.timestamp) as first_seen, MAX(m.timestamp) as last_seen
            FROM message_entities me
            JOIN messages m ON me.message_id = m.id
            WHERE me.entity_id = ?
        """
        
        sql_actors = """
            SELECT DISTINCT m.sender_name, m.sender_id
            FROM message_entities me
            JOIN messages m ON me.message_id = m.id
            WHERE me.entity_id = ? AND m.sender_name IS NOT NULL
            LIMIT 10
        """
        
        sql_groups = """
            SELECT DISTINCT m.group_id, m.group_name
            FROM message_entities me
            JOIN messages m ON me.message_id = m.id
            WHERE me.entity_id = ? AND m.group_name IS NOT NULL
            LIMIT 8
        """
        
        details = {
            "msg_count": 0,
            "first_seen": None,
            "last_seen": None,
            "actors": [],
            "groups": []
        }
        
        try:
            with get_db(self.db_path) as conn:
                m_row = conn.execute(sql_metrics, (entity_id,)).fetchone()
                if m_row and m_row["msg_count"] > 0:
                    details["msg_count"] = m_row["msg_count"]
                    details["first_seen"] = m_row["first_seen"]
                    details["last_seen"] = m_row["last_seen"]
                    
                a_rows = conn.execute(sql_actors, (entity_id,)).fetchall()
                details["actors"] = [dict(r) for r in a_rows]
                
                g_rows = conn.execute(sql_groups, (entity_id,)).fetchall()
                details["groups"] = [dict(r) for r in g_rows]
        except Exception as exc:
            logger.error("get_entity_node_details failed for entity %d: %s", entity_id, exc)
            
        return details

    def get_actor_behavior(self, sender_name: str) -> dict:
        """
        Builds behavioral fingerprinting data for an actor.
        """
        sender_name = sender_name.strip()
        
        sql_cats = """
            SELECT threat_category, COUNT(*) as cat_count
            FROM messages
            WHERE sender_name = ?
            GROUP BY threat_category
        """
        
        sql_groups = """
            SELECT COUNT(DISTINCT group_id) as g_count
            FROM messages
            WHERE sender_name = ?
        """
        
        sql_media = """
            SELECT COUNT(*) as media_count
            FROM messages
            WHERE sender_name = ? AND media_path IS NOT NULL AND media_path != ''
        """
        
        sql_total = """
            SELECT COUNT(*) as total_count
            FROM messages
            WHERE sender_name = ?
        """
        
        sql_urgency = """
            SELECT COUNT(*) as urgency_count
            FROM messages
            WHERE sender_name = ? AND (
                text LIKE '%urgent%' OR text LIKE '%immediately%' OR text LIKE '%right now%' OR
                text LIKE '%asap%' OR text LIKE '%hurry%' OR text LIKE '%action required%' OR
                ocr_text LIKE '%urgent%' OR ocr_text LIKE '%immediately%' OR ocr_text LIKE '%asap%'
            )
        """
        
        sql_hours = """
            SELECT CAST(strftime('%H', timestamp) AS INTEGER) as hr, COUNT(*) as hr_count
            FROM messages
            WHERE sender_name = ?
            GROUP BY hr
        """
        
        res = {
            "categories": {},
            "group_count": 0,
            "media_ratio": 0.0,
            "urgency_bias": 0.0,
            "op_mode": "Human Operator",
            "timezone_inference": "Continuous (Possible automated bot profile)",
            "hour_distribution": [0] * 24
        }
        
        try:
            with get_db(self.db_path) as conn:
                t_row = conn.execute(sql_total, (sender_name,)).fetchone()
                total = t_row["total_count"] if t_row else 0
                if total == 0:
                    return res
                
                for r in conn.execute(sql_cats, (sender_name,)).fetchall():
                    cat = r["threat_category"] or "Benign"
                    res["categories"][cat] = r["cat_count"]
                    
                g_row = conn.execute(sql_groups, (sender_name,)).fetchone()
                res["group_count"] = g_row["g_count"] if g_row else 0
                
                m_row = conn.execute(sql_media, (sender_name,)).fetchone()
                media_cnt = m_row["media_count"] if m_row else 0
                res["media_ratio"] = (media_cnt / total) * 100.0
                
                u_row = conn.execute(sql_urgency, (sender_name,)).fetchone()
                urg_cnt = u_row["urgency_count"] if u_row else 0
                res["urgency_bias"] = (urg_cnt / total) * 100.0
                
                h_rows = conn.execute(sql_hours, (sender_name,)).fetchall()
                active_hours_count = 0
                peak_hour = 0
                peak_count = 0
                
                for r in h_rows:
                    hr = r["hr"]
                    cnt = r["hr_count"]
                    if 0 <= hr < 24:
                        res["hour_distribution"][hr] = cnt
                        active_hours_count += 1
                        if cnt > peak_count:
                            peak_count = cnt
                            peak_hour = hr
                
                if active_hours_count >= 18:
                    res["op_mode"] = "Automated Bot"
                else:
                    res["op_mode"] = "Human Operator"
                    
                offset = 14 - peak_hour
                if offset > 12:
                    offset -= 24
                elif offset < -12:
                    offset += 24
                    
                if offset == 0 or offset == 1:
                    res["timezone_inference"] = "Peak active hours match GMT/BST (Europe / UK / West Africa)"
                elif offset == 2 or offset == 3:
                    res["timezone_inference"] = "Peak active hours match EET/MSK (Eastern Europe / Russia / East Africa)"
                elif 4 <= offset <= 6:
                    res["timezone_inference"] = "Peak active hours match IST/GST (South Asia / India / Middle East)"
                elif 7 <= offset <= 9:
                    res["timezone_inference"] = "Peak active hours match SGT/CST (China / Singapore / East Asia)"
                elif -8 <= offset <= -5:
                    res["timezone_inference"] = "Peak active hours match EST/PST (Americas / USA)"
                else:
                    res["timezone_inference"] = f"Activity peak at {peak_hour:02d}:00 UTC (Estimated offset: UTC{'+' if offset >= 0 else ''}{offset})"
        except Exception as exc:
            logger.error("get_actor_behavior failed for %s: %s", sender_name, exc)
            
        return res


    def get_actor_dossier_db(self, sender_id: str, sender_name: str) -> dict:
        """
        Aggregates all internal intelligence about an actor from the DB.
        Called by the on-demand OSINT dossier endpoint.
        """
        sid = str(sender_id).strip()
        sname = sender_name.strip() if sender_name else ""
        
        # Use OR matching: search by either sender_id or sender_name
        match_clause = "(sender_id = ? OR sender_name = ?)"
        params_pair = (sid, sname)
        
        sql_groups = f"""
            SELECT DISTINCT group_id, group_name
            FROM messages
            WHERE {match_clause} AND group_name IS NOT NULL
        """
        
        sql_phones_posted = f"""
            SELECT DISTINCT e.entity_value
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            WHERE ({match_clause.replace('sender_id', 'm.sender_id').replace('sender_name', 'm.sender_name')})
              AND e.entity_type = 'phone'
        """
        
        sql_upi_posted = f"""
            SELECT DISTINCT e.entity_value
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            WHERE ({match_clause.replace('sender_id', 'm.sender_id').replace('sender_name', 'm.sender_name')})
              AND e.entity_type = 'upi_id'
        """
        
        sql_crypto_posted = f"""
            SELECT DISTINCT e.entity_type, e.entity_value,
                   w.balance, w.total_received, w.is_sanctioned, w.sanction_source
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            LEFT JOIN wallet_enrichments w ON w.entity_id = e.id
            WHERE ({match_clause.replace('sender_id', 'm.sender_id').replace('sender_name', 'm.sender_name')})
              AND e.entity_type LIKE 'crypto_%'
            LIMIT 20
        """
        
        sql_email_posted = f"""
            SELECT DISTINCT e.entity_value
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            WHERE ({match_clause.replace('sender_id', 'm.sender_id').replace('sender_name', 'm.sender_name')})
              AND e.entity_type = 'email'
        """
        
        sql_phone_enrichment = """
            SELECT pe.carrier_name, pe.country_code, pe.phone_type, pe.region
            FROM phone_enrichments pe
            JOIN entities e ON pe.entity_id = e.id
            JOIN message_entities me ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            WHERE (m.sender_id = ? OR m.sender_name = ?)
              AND e.entity_type = 'phone'
            LIMIT 1
        """
        
        result = {
            "groups": [],
            "phones_posted": [],
            "upi_posted": [],
            "crypto_posted": [],
            "emails_posted": [],
            "phone_enrichment": None,
        }
        
        try:
            with get_db(self.db_path) as conn:
                result["groups"] = [dict(r) for r in conn.execute(sql_groups, params_pair).fetchall()]
                result["phones_posted"] = [r[0] for r in conn.execute(sql_phones_posted, params_pair + params_pair).fetchall()]
                result["upi_posted"] = [r[0] for r in conn.execute(sql_upi_posted, params_pair + params_pair).fetchall()]
                result["emails_posted"] = [r[0] for r in conn.execute(sql_email_posted, params_pair + params_pair).fetchall()]
                
                crypto_rows = conn.execute(sql_crypto_posted, params_pair + params_pair).fetchall()
                result["crypto_posted"] = [dict(r) for r in crypto_rows]
                
                pe_row = conn.execute(sql_phone_enrichment, params_pair).fetchone()
                if pe_row:
                    result["phone_enrichment"] = dict(pe_row)
        except Exception as exc:
            logger.error("get_actor_dossier_db failed for %s/%s: %s", sender_id, sender_name, exc)
            
        return result


    def get_cached_threat_points(self) -> list:
        """
        Retrieves all already-geocoded threat points using a single SQL JOIN.
        Very fast, runs in <10ms.
        """
        sql = """
            SELECT DISTINCT e.id, e.entity_type, e.entity_value, m.sender_name, m.group_name, m.risk_score,
                            g.latitude, g.longitude, g.country, g.city
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            JOIN geocodes g ON g.entity_id = e.id
            WHERE e.entity_type IN ('phone_number', 'ip_address')
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_cached_threat_points failed: %s", exc)
            return []

    def get_ungeocoded_threat_points(self) -> list:
        """
        Finds all threat phone and IP entities that do not have cache entries yet.
        """
        sql = """
            SELECT DISTINCT e.id, e.entity_type, e.entity_value, m.sender_name, m.group_name, m.risk_score
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            LEFT JOIN geocodes g ON g.entity_id = e.id
            WHERE e.entity_type IN ('phone_number', 'ip_address') AND g.entity_id IS NULL
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_ungeocoded_threat_points failed: %s", exc)
            return []


    def get_actor_risk_tier(self, actor_id: str) -> str:
        """Retrieves the risk tier for a given actor ID."""
        sql = "SELECT risk_tier FROM sender_profiles WHERE sender_id = ?"
        try:
            with get_db(self.db_path) as conn:
                row = conn.execute(sql, (actor_id,)).fetchone()
                if row:
                    return row["risk_tier"]
        except Exception:
            pass
        return "Medium"


    def lookup_leak_entity(self, entity_value: str) -> dict | None:
        """Lookup an entity inside the Dark Web leak registry."""
        sql = "SELECT source_leak, leak_date, details FROM leak_registry WHERE entity_value = ?"
        try:
            with get_db(self.db_path) as conn:
                row = conn.execute(sql, (entity_value.strip(),)).fetchone()
                if row:
                    return dict(row)
        except Exception as e:
            logger.warning("Error checking leak registry: %s", e)
        return None

    def get_actor_aliases(self, sender_name: str) -> list:
        """
        Calculates potential threat actor aliases based on shared IOC postings
        (crypto wallets, phone numbers, email, telegram handles) and timezone correlation.
        """
        sender_name = sender_name.strip()
        if not sender_name:
            return []

        # Step 1: Find all entities posted by this sender
        sql_sender_entities = """
            SELECT DISTINCT e.id, e.entity_type, e.entity_value
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            WHERE m.sender_name = ?
        """
        
        # Step 2: Retrieve behavior distribution for hourly correlation
        my_behavior = self.get_actor_behavior(sender_name)
        my_hours = my_behavior.get("hour_distribution", [0]*24)
        my_sum = sum(my_hours)

        aliases = {}
        try:
            with get_db(self.db_path) as conn:
                my_ents = conn.execute(sql_sender_entities, (sender_name,)).fetchall()
                if not my_ents:
                    return []
                
                # For each entity, find who else posted it
                for ent in my_ents:
                    eid = ent["id"]
                    etype = ent["entity_type"]
                    evalue = ent["entity_value"]
                    
                    sql_other_posters = """
                        SELECT DISTINCT m.sender_name
                        FROM message_entities me
                        JOIN messages m ON me.message_id = m.id
                        WHERE me.entity_id = ? AND m.sender_name != ? AND m.sender_name != ''
                    """
                    others = conn.execute(sql_other_posters, (eid, sender_name)).fetchall()
                    for other in others:
                        oname = other["sender_name"]
                        if oname not in aliases:
                            aliases[oname] = {
                                "sender_name": oname,
                                "shared_ioc_count": 0,
                                "reasons": [],
                                "confidence": 0
                            }
                        
                        weight = 30
                        reason_prefix = "Shared IOC"
                        if etype.startswith("crypto_"):
                            weight = 50
                            reason_prefix = "Shared Crypto Wallet"
                        elif etype == "phone_number":
                            weight = 50
                            reason_prefix = "Shared Phone Number"
                        elif etype == "upi_id":
                            weight = 40
                            reason_prefix = "Shared UPI Identifier"
                        elif etype == "telegram_handle":
                            weight = 40
                            reason_prefix = "Shared Telegram Handle"
                            
                        aliases[oname]["shared_ioc_count"] += 1
                        aliases[oname]["reasons"].append(f"{reason_prefix} ({evalue})")
                        aliases[oname]["confidence"] += weight

            # Step 3: Run temporal hourly correlation checks for suspected aliases
            for oname, info in list(aliases.items()):
                other_behavior = self.get_actor_behavior(oname)
                other_hours = other_behavior.get("hour_distribution", [0]*24)
                other_sum = sum(other_hours)
                
                # Check timezone match
                if my_behavior.get("timezone_inference") == other_behavior.get("timezone_inference") and my_behavior.get("timezone_inference") != "Unknown":
                    info["confidence"] += 15
                    info["reasons"].append(f"Matching operational timezone region ({my_behavior.get('timezone_inference')})")

                # Correlation overlap metric
                if my_sum > 0 and other_sum > 0:
                    overlap_score = 0
                    for h in range(24):
                        my_p = my_hours[h] / my_sum
                        other_p = other_hours[h] / other_sum
                        overlap_score += min(my_p, other_p)
                    
                    if overlap_score >= 0.65:
                        info["confidence"] += 20
                        info["reasons"].append(f"High posting hours schedule overlap ({overlap_score*100:.0f}%)")

                # Cap confidence to 98%
                info["confidence"] = min(info["confidence"], 98)
                
            # Filter matches and sort by confidence descending
            matches = [v for v in aliases.values() if v["confidence"] >= 20]
            matches.sort(key=lambda x: x["confidence"], reverse=True)
            return matches
        except Exception as exc:
            logger.error("get_actor_aliases failed for %s: %s", sender_name, exc)
            return []

    def get_actor_ioc_timeline(self, sender_name: str) -> list:
        """
        Compiles a chronological history of all threat entities (IOCs) posted by the actor.
        """
        sender_name = sender_name.strip()
        sql = """
            SELECT DISTINCT e.entity_type, e.entity_value, m.timestamp, m.id as message_id, m.group_name, m.risk_score
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            JOIN messages m ON me.message_id = m.id
            WHERE m.sender_name = ?
            ORDER BY m.timestamp ASC
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, (sender_name,)).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_actor_ioc_timeline failed for %s: %s", sender_name, exc)
            return []

    def get_messages_since_id(self, last_id: int) -> list:
        """Retrieve new threat messages since last message row ID."""
        sql = """
            SELECT id, timestamp, sender_name, group_name, text, threat_category, risk_score
            FROM messages
            WHERE id > ?
            ORDER BY id ASC
            LIMIT 100
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, (last_id,)).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_messages_since_id failed for ID %d: %s", last_id, exc)
            return []





    def get_wallet_enrichment(self, entity_value: str) -> dict | None:
        """Retrieve wallet enrichment details by address value."""
        sql = """
            SELECT w.*, e.entity_value, e.entity_type
            FROM wallet_enrichments w
            JOIN entities e ON w.entity_id = e.id
            WHERE e.entity_value = ?
        """
        try:
            with get_db(self.db_path) as conn:
                row = conn.execute(sql, (entity_value.strip(),)).fetchone()
            return dict(row) if row else None
        except Exception as exc:
            logger.error("get_wallet_enrichment failed: %s", exc)
            return None

    def get_message_entities(self, message_row_id: int) -> list:
        """Get all entities associated with a message."""
        sql = """
            SELECT e.id, e.entity_type, e.entity_value, me.position_in_text,
                   w.balance, w.tx_count, w.is_sanctioned, w.last_enriched_at,
                   p.country_name, p.location, p.carrier, p.is_valid, p.last_enriched_at AS phone_last_enriched
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            LEFT JOIN wallet_enrichments w ON e.id = w.entity_id
            LEFT JOIN phone_enrichments p ON e.id = p.entity_id
            WHERE me.message_id = ?
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, (message_row_id,)).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_message_entities failed: %s", exc)
            return []

    def get_forward_relationships(self, fetched_by: Optional[str] = None) -> list:
        """Retrieve source -> target group forward counts."""
        clauses = ["is_forwarded = 1", "forward_from_id IS NOT NULL"]
        params = []
        if fetched_by:
            clauses.append("fetched_by = ?")
            params.append(fetched_by)
            
        where = "WHERE " + " AND ".join(clauses)
        sql = f"""
            SELECT 
                forward_from_id AS source_id,
                forward_from_name AS source_name,
                group_id AS target_id,
                group_name AS target_name,
                COUNT(*) AS forward_count
            FROM messages
            {where}
            GROUP BY forward_from_id, group_id
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_forward_relationships failed: %s", exc)
            return []

    def get_temporal_distribution(self, group_id: Optional[int] = None, fetched_by: Optional[str] = None) -> list:
        """Retrieve count of messages grouped by hour-of-day (00-23)."""
        clauses = []
        params = []
        if group_id is not None:
            clauses.append("group_id = ?")
            params.append(group_id)
        if fetched_by:
            clauses.append("fetched_by = ?")
            params.append(fetched_by)
            
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT 
                substr(timestamp, 12, 2) AS hour,
                COUNT(*) AS msg_count
            FROM messages
            {where}
            GROUP BY hour ORDER BY hour ASC
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_temporal_distribution failed: %s", exc)
            return []

    def update_message_semantic_info(self, message_row_id: int, campaign_id: str, threat_category: str) -> None:
        """Update campaign ID and threat category for a single message."""
        sql = "UPDATE messages SET campaign_id=?, threat_category=? WHERE id=?"
        try:
            with get_db(self.db_path) as conn:
                conn.execute(sql, (campaign_id, threat_category, message_row_id))
        except Exception as exc:
            logger.error("update_message_semantic_info failed: %s", exc)

    def upsert_campaign(self, campaign_id: str, name: str, first_seen: str, last_seen: str, threat_category: str, rep_text: str) -> None:
        """Upsert a threat campaign cluster."""
        sql = """
            INSERT INTO campaigns (id, campaign_name, first_seen_at, last_seen_at, threat_category, representative_text)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                threat_category = excluded.threat_category,
                representative_text = COALESCE(excluded.representative_text, representative_text)
        """
        try:
            with get_db(self.db_path) as conn:
                conn.execute(sql, (campaign_id, name, first_seen, last_seen, threat_category, rep_text))
        except Exception as exc:
            logger.error("upsert_campaign failed: %s", exc)

    def get_campaigns(self) -> list:
        """Retrieve all campaigns with member message counts."""
        sql = """
            SELECT c.*, COUNT(m.id) AS message_count
            FROM campaigns c
            LEFT JOIN messages m ON c.id = m.campaign_id
            GROUP BY c.id
            ORDER BY c.last_seen_at DESC
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_campaigns failed: %s", exc)
            return []

    def get_campaign_messages(self, campaign_id: str) -> list:
        """Retrieve all messages belonging to a specific campaign."""
        sql = """
            SELECT * FROM messages
            WHERE campaign_id = ?
            ORDER BY timestamp DESC
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, (campaign_id,)).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_campaign_messages failed: %s", exc)
            return []

    def update_message_media_info(self, message_row_id: int, media_path: str, ocr_text: str, phash: str, qr_codes: list) -> None:
        """Update message row with parsed media metrics."""
        sql = """
            UPDATE messages
            SET media_path=?, ocr_text=?, phash=?, qr_codes=?
            WHERE id=?
        """
        qr_str = json.dumps(qr_codes) if qr_codes else None
        try:
            with get_db(self.db_path) as conn:
                conn.execute(sql, (media_path, ocr_text, phash, qr_str, message_row_id))
        except Exception as exc:
            logger.error("update_message_media_info failed for %d: %s", message_row_id, exc)

    def get_similar_images(self, target_phash: str, max_distance: int = 10) -> list:
        """Find messages with visually similar images by comparing pHash hamming distance."""
        try:
            import imagehash
            target = imagehash.hex_to_hash(target_phash)
        except Exception as exc:
            logger.error("Invalid target pHash %s: %s", target_phash, exc)
            return []
            
        sql = """
            SELECT id, message_id, group_id, group_name, sender_name, timestamp, media_path, phash 
            FROM messages 
            WHERE phash IS NOT NULL
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql).fetchall()
            
            similar = []
            for r in rows:
                try:
                    h = imagehash.hex_to_hash(r["phash"])
                    dist = target - h
                    if dist <= max_distance:
                        d = dict(r)
                        d["distance"] = dist
                        similar.append(d)
                except Exception:
                    continue
            
            # Sort by distance
            similar.sort(key=lambda x: x["distance"])
            return similar
        except Exception as exc:
            logger.error("get_similar_images failed: %s", exc)
            return []

    def get_message_by_row_id(self, row_id: int) -> dict | None:
        """Fetch a single message dictionary by its row ID, including its entities."""
        sql = "SELECT * FROM messages WHERE id = ?"
        try:
            with get_db(self.db_path) as conn:
                row = conn.execute(sql, (row_id,)).fetchone()
            if row:
                d = dict(row)
                d["entities"] = self.get_message_entities(row_id)
                return d
            return None
        except Exception as exc:
            logger.error("get_message_by_row_id failed for %d: %s", row_id, exc)
            return None

    def update_message_risk_score(self, message_row_id: int, risk_score: float) -> None:
        """Update message row with calculated composite risk score."""
        sql = "UPDATE messages SET risk_score = ? WHERE id = ?"
        try:
            with get_db(self.db_path) as conn:
                conn.execute(sql, (risk_score, message_row_id))
        except Exception as exc:
            logger.error("update_message_risk_score failed for %d: %s", message_row_id, exc)

    def update_sender_profile(self, sender_id: str, sender_phone: str, message_risk: float, timestamp: str) -> None:
        """Upsert sender profile accumulating risk stats over time."""
        if not sender_id:
            return
            
        select_sql = "SELECT total_messages, cumulative_risk FROM sender_profiles WHERE sender_id = ?"
        insert_sql = """
            INSERT INTO sender_profiles (sender_id, sender_phone, total_messages, cumulative_risk, average_risk, last_seen_at, risk_tier)
            VALUES (?, ?, 1, ?, ?, ?, ?)
        """
        update_sql = """
            UPDATE sender_profiles
            SET sender_phone = COALESCE(?, sender_phone),
                total_messages = total_messages + 1,
                cumulative_risk = cumulative_risk + ?,
                average_risk = ?,
                last_seen_at = ?,
                risk_tier = ?
            WHERE sender_id = ?
        """
        
        try:
            with get_db(self.db_path) as conn:
                row = conn.execute(select_sql, (sender_id,)).fetchone()
                if row:
                    total = row["total_messages"] + 1
                    cum_risk = row["cumulative_risk"] + message_risk
                    avg_risk = cum_risk / total
                    
                    if avg_risk >= 80:
                        tier = "Critical"
                    elif avg_risk >= 60:
                        tier = "High"
                    elif avg_risk >= 30:
                        tier = "Medium"
                    else:
                        tier = "Low"
                        
                    conn.execute(update_sql, (sender_phone, message_risk, avg_risk, timestamp, tier, sender_id))
                else:
                    avg_risk = message_risk
                    if avg_risk >= 80:
                        tier = "Critical"
                    elif avg_risk >= 60:
                        tier = "High"
                    elif avg_risk >= 30:
                        tier = "Medium"
                    else:
                        tier = "Low"
                    conn.execute(insert_sql, (sender_id, sender_phone, message_risk, avg_risk, timestamp, tier))
        except Exception as exc:
            logger.error("update_sender_profile failed for %s: %s", sender_id, exc)

    def get_high_risk_actors(self, limit: int = 20, fetched_by: Optional[str] = None) -> list:
        """Retrieve actors ordered by cumulative risk score."""
        if fetched_by:
            sql = """
                SELECT sp.* FROM sender_profiles sp
                WHERE sp.sender_id IN (
                    SELECT DISTINCT sender_name FROM messages WHERE fetched_by = ? AND sender_name IS NOT NULL AND sender_name != ''
                )
                ORDER BY sp.cumulative_risk DESC LIMIT ?
            """
            params = (fetched_by, limit)
        else:
            sql = "SELECT * FROM sender_profiles ORDER BY cumulative_risk DESC LIMIT ?"
            params = (limit,)
            
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_high_risk_actors failed: %s", exc)
            return []

    # ── Cases & Watchlists (Phase 6) ──────────────────────────────────────────

    def create_case(self, case_id: str, title: str, description: str, created_at: str) -> None:
        """Create a new analyst investigation case folder."""
        sql = "INSERT INTO cases (id, title, description, created_at) VALUES (?, ?, ?, ?)"
        try:
            with get_db(self.db_path) as conn:
                conn.execute(sql, (case_id, title, description, created_at))
        except Exception as exc:
            logger.error("create_case failed: %s", exc)

    def delete_case(self, case_id: str) -> None:
        """Delete case folder and cascaded case items."""
        sql = "DELETE FROM cases WHERE id = ?"
        try:
            with get_db(self.db_path) as conn:
                conn.execute(sql, (case_id,))
        except Exception as exc:
            logger.error("delete_case failed: %s", exc)

    def add_item_to_case(self, case_id: str, item_type: str, item_value: str, added_at: str) -> None:
        """Add message row ID, wallet, or sender name to case folder. Ignores duplicates."""
        select_sql = "SELECT id FROM case_items WHERE case_id = ? AND item_type = ? AND item_value = ?"
        insert_sql = "INSERT INTO case_items (case_id, item_type, item_value, added_at) VALUES (?, ?, ?, ?)"
        try:
            with get_db(self.db_path) as conn:
                row = conn.execute(select_sql, (case_id, item_type, item_value)).fetchone()
                if not row:
                    conn.execute(insert_sql, (case_id, item_type, item_value, added_at))
        except Exception as exc:
            logger.error("add_item_to_case failed: %s", exc)

    def remove_item_from_case(self, item_row_id: int) -> None:
        """Remove a grouped item from investigation case."""
        sql = "DELETE FROM case_items WHERE id = ?"
        try:
            with get_db(self.db_path) as conn:
                conn.execute(sql, (item_row_id,))
        except Exception as exc:
            logger.error("remove_item_from_case failed: %s", exc)

    def get_cases(self) -> list:
        """Retrieve all cases sorted by creation date."""
        sql = "SELECT * FROM cases ORDER BY created_at DESC"
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_cases failed: %s", exc)
            return []

    def get_case_details(self, case_id: str) -> dict | None:
        """Retrieve case meta info and list of grouped case items."""
        sql_case = "SELECT * FROM cases WHERE id = ?"
        sql_items = "SELECT * FROM case_items WHERE case_id = ? ORDER BY added_at DESC"
        try:
            with get_db(self.db_path) as conn:
                case_row = conn.execute(sql_case, (case_id,)).fetchone()
                if not case_row:
                    return None
                
                res = dict(case_row)
                item_rows = conn.execute(sql_items, (case_id,)).fetchall()
                
                items = []
                for item in item_rows:
                    item_dict = dict(item)
                    if item["item_type"] == "message":
                        # Fetch simple representation of message
                        msg = conn.execute(
                            "SELECT text, timestamp, sender_name, group_name, risk_score FROM messages WHERE id = ?",
                            (item["item_value"],)
                        ).fetchone()
                        if msg:
                            item_dict["message_details"] = dict(msg)
                    items.append(item_dict)
                res["items"] = items
                return res
        except Exception as exc:
            logger.error("get_case_details failed for %s: %s", case_id, exc)
            return None

    def save_watchlist(self, watchlist_id: str, name: str, query_params: dict, created_at: str) -> None:
        """Save a search filter query to watchlists database."""
        sql = "INSERT INTO watchlists (id, name, query_params, created_at) VALUES (?, ?, ?, ?)"
        try:
            params_str = json.dumps(query_params)
            with get_db(self.db_path) as conn:
                conn.execute(sql, (watchlist_id, name, params_str, created_at))
        except Exception as exc:
            logger.error("save_watchlist failed: %s", exc)

    def delete_watchlist(self, watchlist_id: str) -> None:
        """Delete watchlist item by ID."""
        sql = "DELETE FROM watchlists WHERE id = ?"
        try:
            with get_db(self.db_path) as conn:
                conn.execute(sql, (watchlist_id,))
        except Exception as exc:
            logger.error("delete_watchlist failed: %s", exc)

    def get_watchlists(self) -> list:
        """Retrieve saved watchlists."""
        sql = "SELECT * FROM watchlists ORDER BY created_at DESC"
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql).fetchall()
            
            res = []
            for r in rows:
                d = dict(r)
                try:
                    d["query_params"] = json.loads(d["query_params"])
                except Exception:
                    d["query_params"] = {}
                res.append(d)
            return res
        except Exception as exc:
            logger.error("get_watchlists failed: %s", exc)
            return []

    def get_telegram_accounts(self) -> list[dict]:
        """Retrieve all registered accounts configuration."""
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute("SELECT * FROM telegram_accounts").fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_telegram_accounts failed: %s", exc)
            return []

    def upsert_telegram_account(self, phone: str, api_id: int, api_hash: str, session_name: str, is_active: int = 1, status: str = 'disconnected') -> bool:
        """Upsert a Telegram account configuration."""
        try:
            with get_db(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO telegram_accounts (phone, api_id, api_hash, session_name, is_active, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(phone) DO UPDATE SET
                        api_id=excluded.api_id,
                        api_hash=excluded.api_hash,
                        session_name=excluded.session_name,
                        is_active=excluded.is_active,
                        status=excluded.status
                """, (phone, api_id, api_hash, session_name, is_active, status))
            return True
        except Exception as exc:
            logger.error("upsert_telegram_account failed: %s", exc)
            return False

    def delete_telegram_account(self, phone: str) -> bool:
        """Remove a Telegram account configuration."""
        try:
            with get_db(self.db_path) as conn:
                conn.execute("DELETE FROM telegram_accounts WHERE phone = ?", (phone,))
            return True
        except Exception as exc:
            logger.error("delete_telegram_account failed: %s", exc)
            return False

    def update_telegram_account_status(self, phone: str, status: str) -> bool:
        """Update active status code for account client."""
        try:
            with get_db(self.db_path) as conn:
                conn.execute("UPDATE telegram_accounts SET status = ? WHERE phone = ?", (status, phone))
            return True
        except Exception as exc:
            logger.error("update_telegram_account_status failed: %s", exc)
            return False

    def update_telegram_account_active(self, phone: str, is_active: int) -> bool:
        """Enable or disable individual account fetches."""
        try:
            with get_db(self.db_path) as conn:
                conn.execute("UPDATE telegram_accounts SET is_active = ? WHERE phone = ?", (is_active, phone))
            return True
        except Exception as exc:
            logger.error("update_telegram_account_active failed: %s", exc)
            return False

    def get_heatmap_data(
        self,
        keyword=None,
        group_id=None,
        datetime_from: Optional[str] = None,
        datetime_to: Optional[str] = None,
        fetched_by: Optional[str] = None,
    ) -> list:
        """
        Return message counts and average risk score bucketed by
        day_of_week (0=Mon … 6=Sun) × hour_of_day (0–23).
        Each row: {day, hour, count, avg_risk}
        """
        filters = []
        params  = []

        if keyword:
            if isinstance(keyword, list):
                placeholders = ",".join("?" * len(keyword))
                filters.append(f"matched_keyword IN ({placeholders})")
                params.extend(keyword)
            else:
                filters.append("matched_keyword = ?")
                params.append(keyword)

        if group_id:
            if isinstance(group_id, list):
                placeholders = ",".join("?" * len(group_id))
                filters.append(f"group_id IN ({placeholders})")
                params.extend(group_id)
            else:
                filters.append("group_id = ?")
                params.append(group_id)

        if datetime_from:
            filters.append("timestamp >= ?")
            params.append(_normalise_dt(datetime_from, end=False))
        if datetime_to:
            filters.append("timestamp <= ?")
            params.append(_normalise_dt(datetime_to, end=True))
        if fetched_by:
            filters.append("fetched_by = ?")
            params.append(fetched_by)

        where = ("WHERE " + " AND ".join(filters)) if filters else ""

        sql = f"""
            SELECT
                CAST(strftime('%w', timestamp) AS INTEGER) AS dow,
                CAST(strftime('%H', timestamp) AS INTEGER) AS hour,
                COUNT(*)                                   AS cnt,
                COALESCE(AVG(risk_score), 0.0)             AS avg_risk
            FROM messages
            {where}
            GROUP BY dow, hour
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "day":      (row["dow"] + 6) % 7,  # SQLite %w: 0=Sun → convert to 0=Mon
                    "hour":     row["hour"],
                    "count":    row["cnt"],
                    "avg_risk": round(row["avg_risk"], 1),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error("get_heatmap_data failed: %s", exc)
            return []

    def get_ioc_pivot(self, entity_type: str, entity_value: str) -> list:
        """
        Return all messages that reference a given IOC (entity_value).
        Optionally filtered by entity_type.
        """
        params = [entity_value]
        type_filter = ""
        if entity_type:
            type_filter = "AND e.entity_type = ?"
            params.append(entity_type)

        sql = f"""
            SELECT
                m.id, m.message_id, m.group_name, m.group_id,
                m.sender_name, m.sender_id, m.timestamp,
                m.text, m.matched_keyword, m.threat_category,
                m.risk_score, m.is_matched,
                e.entity_type, e.entity_value
            FROM messages m
            JOIN message_entities me ON me.message_id = m.id
            JOIN entities e          ON e.id = me.entity_id
            WHERE e.entity_value = ?
            {type_filter}
            ORDER BY m.timestamp DESC
            LIMIT 200
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_ioc_pivot failed: %s", exc)
            return []

    def get_keyword_effectiveness(self) -> list:
        """
        Calculate metrics for keywords:
        - Keyword string
        - Total matched messages count
        - High-risk messages count
        - Average risk score
        """
        sql = """
            SELECT 
                k.keyword,
                COUNT(m.id) AS total_hits,
                SUM(CASE WHEN m.risk_score >= 70 THEN 1 ELSE 0 END) AS high_risk_hits,
                COALESCE(AVG(m.risk_score), 0.0) AS avg_risk
            FROM keywords k
            LEFT JOIN messages m ON k.keyword = m.matched_keyword AND m.is_matched = 1
            GROUP BY k.keyword
            ORDER BY total_hits DESC
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_keyword_effectiveness failed: %s", exc)
            return []

    # ── Group Discovery ────────────────────────────────────────────────────────

    def save_pending_group(
        self,
        group_id: int | None,
        group_name: str,
        group_username: str | None,
        member_count: int,
        invite_link: str | None,
        source: str,
        source_keyword: str | None,
        discovered_at: str,
        context_text: str | None = None,
    ) -> bool:
        """
        Save a newly discovered group to pending_groups for analyst review.
        Returns True if inserted (False if already exists).
        Deduplicates on (group_id, group_name, invite_link).
        """
        sql = """
            INSERT OR IGNORE INTO pending_groups
                (group_id, group_name, group_username, member_count,
                 invite_link, source, source_keyword, discovered_at, status, context_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """
        try:
            with get_db(self.db_path) as conn:
                cur = conn.execute(
                    sql,
                    (group_id, group_name, group_username, member_count,
                     invite_link, source, source_keyword, discovered_at, context_text),
                )
            return cur.rowcount > 0
        except Exception as exc:
            logger.error("save_pending_group failed: %s", exc)
            return False

    def get_pending_groups(self, status: str = "pending") -> list:
        """Return pending discovered groups, newest first."""
        sql = """
            SELECT * FROM pending_groups
            WHERE status = ?
            ORDER BY discovered_at DESC
        """
        try:
            with get_db(self.db_path) as conn:
                rows = conn.execute(sql, (status,)).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("get_pending_groups failed: %s", exc)
            return []

    def get_pending_groups_count(self) -> int:
        """Return count of pending (unreviewed) discovered groups."""
        try:
            with get_db(self.db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM pending_groups WHERE status = 'pending'"
                ).fetchone()
            return row[0] if row else 0
        except Exception as exc:
            logger.error("get_pending_groups_count failed: %s", exc)
            return 0

    def update_pending_group_status(self, pending_id: int, status: str) -> None:
        """Set status of a pending group to 'approved' or 'dismissed'."""
        try:
            with get_db(self.db_path) as conn:
                conn.execute(
                    "UPDATE pending_groups SET status = ? WHERE id = ?",
                    (status, pending_id),
                )
        except Exception as exc:
            logger.error("update_pending_group_status failed: %s", exc)

    def is_group_known(self, group_id: int | None, group_name: str | None,
                       invite_link: str | None) -> bool:
        """
        Returns True if a group is already monitored OR already pending/approved.
        Used to avoid re-queuing duplicates during discovery scans.
        """
        try:
            with get_db(self.db_path) as conn:
                if group_id:
                    row = conn.execute(
                        "SELECT 1 FROM groups WHERE group_id = ? LIMIT 1", (group_id,)
                    ).fetchone()
                    if row:
                        return True
                    row = conn.execute(
                        "SELECT 1 FROM pending_groups WHERE group_id = ? AND status != 'dismissed' LIMIT 1",
                        (group_id,),
                    ).fetchone()
                    if row:
                        return True
                if invite_link:
                    row = conn.execute(
                        "SELECT 1 FROM pending_groups WHERE invite_link = ? AND status != 'dismissed' LIMIT 1",
                        (invite_link,),
                    ).fetchone()
                    if row:
                        return True
            return False
        except Exception as exc:
            logger.error("is_group_known failed: %s", exc)
            return False



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_dt(value: str, end: bool) -> str:
    """
    Accept flexible date/datetime strings from the UI and return a
    full ISO-8601 string suitable for lexicographic timestamp comparison.

    Examples:
      '2024-07-23'           + end=False  -> '2024-07-23T00:00:00'
      '2024-07-23'           + end=True   -> '2024-07-23T23:59:59'
      '2024-07-23T09:00'     + end=False  -> '2024-07-23T09:00:00'
      '2024-07-23T21:00'     + end=True   -> '2024-07-23T21:00:59'
      '2024-07-23T09:00:00'  (any)        -> unchanged
    """
    v = value.strip()
    if len(v) == 10:                          # 'YYYY-MM-DD'
        return v + ("T23:59:59" if end else "T00:00:00")
    if len(v) == 16:                          # 'YYYY-MM-DDTHH:MM'
        return v + (":59" if end else ":00")
    return v                                   # already full or unknown format
