"""Migrate existing SQLite DB to new schema."""
import sqlite3, os
import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

db_path = "data/telegram_intel.db"
try:
    with open("config/config.yaml", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
        if config and "db_path" in config:
            db_path = config["db_path"]
except Exception:
    pass

os.makedirs(os.path.dirname(db_path), exist_ok=True)
conn = sqlite3.connect(db_path)

# Introspect existing schema
msg_cols  = [r[1] for r in conn.execute('PRAGMA table_info(messages)').fetchall()]
grp_cols  = [r[1] for r in conn.execute('PRAGMA table_info(groups)').fetchall()]
tables    = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

print('Existing messages columns:', msg_cols)
print('Existing groups columns:', grp_cols)
print('Tables:', tables)

# Add new columns to messages if missing
if 'forward_from_name' not in msg_cols:
    conn.execute('ALTER TABLE messages ADD COLUMN forward_from_name TEXT')
    print('Added: messages.forward_from_name')
if 'forward_from_id' not in msg_cols:
    conn.execute('ALTER TABLE messages ADD COLUMN forward_from_id INTEGER')
    print('Added: messages.forward_from_id')
if 'sender_id' not in msg_cols:
    conn.execute('ALTER TABLE messages ADD COLUMN sender_id TEXT')
    print('Added: messages.sender_id')

# Add new column to groups if missing
if 'last_message_at' not in grp_cols:
    conn.execute('ALTER TABLE groups ADD COLUMN last_message_at TEXT')
    print('Added: groups.last_message_at')

# Create pipeline_events table if missing
if 'pipeline_events' not in tables:
    conn.execute('''CREATE TABLE pipeline_events (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type       TEXT    NOT NULL,
        started_at       TEXT    NOT NULL,
        ended_at         TEXT,
        duration_seconds REAL,
        details          TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_evt_type_started ON pipeline_events(event_type, started_at)')
    print('Created: pipeline_events table + index')

# Create missing indexes
conn.execute('CREATE INDEX IF NOT EXISTS idx_msg_fwd_id ON messages(forward_from_id)')
print('Index: idx_msg_fwd_id ensured')
conn.execute('CREATE INDEX IF NOT EXISTS idx_msg_sender_id ON messages(sender_id)')
print('Index: idx_msg_sender_id ensured')

conn.commit()
conn.close()
print('Migration complete.')
