import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.storage.database import DatabaseHandler, init_db

def main():
    db_path = tempfile.mktemp(suffix=".db")
    print("Temporary DB:", db_path)
    
    init_db(db_path)
    db = DatabaseHandler(db_path)
    
    from src.storage.database import get_db
    with get_db(db_path) as conn:
        res = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='phone_enrichments'").fetchone()
        print("phone_enrichments table exists:", bool(res))
    
    test_phones = [
        {"type": "phone_number", "value": "+919876543210", "position": 10},
        {"type": "phone_number", "value": "+14155552671", "position": 25}
    ]
    
    msg_id = 999
    now = datetime.now(timezone.utc).isoformat()
    
    print("Saving entities...")
    db.save_message_entities(msg_id, test_phones, now)
    
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM phone_enrichments").fetchall()
        print("Enriched rows in DB count:", len(rows))
        for r in rows:
            print("Row:", dict(r))
            
    entities = db.get_message_entities(msg_id)
    print("Retrieved message entities:")
    for ent in entities:
        print("Entity:", ent)
        if ent["entity_type"] == "phone_number":
            assert ent["country_name"] is not None
            assert ent["carrier"] is not None
            
    print("PHONE ENRICHMENT VERIFICATION SUCCESSFUL!")
    os.remove(db_path)

if __name__ == "__main__":
    main()
