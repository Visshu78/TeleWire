import unittest
import os
import shutil
import tempfile
import sqlite3
from datetime import datetime, timezone

from src.storage.database import init_db, DatabaseHandler, _normalise_dt
from src.processing.deduplicator import Deduplicator
from src.processing.keyword_matcher import KeywordMatcher


class TestPipelineDatabase(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test DB
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_telegram_intel.db")
        init_db(self.db_path)
        self.db = DatabaseHandler(self.db_path)

    def tearDown(self):
        # Clean up database files
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_db_initialization(self):
        # Verify the tables exist
        with sqlite3.connect(self.db_path) as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            self.assertIn("messages", tables)
            self.assertIn("groups", tables)
            self.assertIn("keywords", tables)
            self.assertIn("pipeline_events", tables)

    def test_date_normalisation(self):
        self.assertEqual(_normalise_dt("2026-07-03", False), "2026-07-03T00:00:00")
        self.assertEqual(_normalise_dt("2026-07-03", True), "2026-07-03T23:59:59")
        self.assertEqual(_normalise_dt("2026-07-03T15:30", False), "2026-07-03T15:30:00")
        self.assertEqual(_normalise_dt("2026-07-03T15:30", True), "2026-07-03T15:30:59")

    def test_insert_messages_batch_and_deduplication(self):
        # Seed a group
        self.db.upsert_group(12345, "Test Group", "group", 10)
        
        # Test batch insert
        msg1 = {
            "message_id": 1,
            "group_id": 12345,
            "group_name": "Test Group",
            "sender_name": "Alice",
            "sender_phone": None,
            "text": "Hello world, investment scam!",
            "language": "en",
            "is_forwarded": 0,
            "forward_from_name": None,
            "forward_from_id": None,
            "matched_keyword": "investment scam",
            "fuzzy_score": 100.0,
            "is_matched": 1,
            "timestamp": "2026-07-03T12:00:00+00:00",
            "hash": "hash1"
        }
        msg2 = {
            "message_id": 2,
            "group_id": 12345,
            "group_name": "Test Group",
            "sender_name": "Bob",
            "sender_phone": None,
            "text": "Regular message",
            "language": "en",
            "is_forwarded": 0,
            "forward_from_name": None,
            "forward_from_id": None,
            "matched_keyword": None,
            "fuzzy_score": 0.0,
            "is_matched": 0,
            "timestamp": "2026-07-03T12:05:00+00:00",
            "hash": "hash2"
        }
        
        inserted = self.db.insert_messages_batch([msg1, msg2])
        self.assertEqual(inserted, 2)
        
        # Verify deduplication - duplicate hash should be ignored
        msg3 = dict(msg2)
        msg3["message_id"] = 3
        msg3["hash"] = "hash2"  # duplicate hash
        
        inserted_dup = self.db.insert_messages_batch([msg3])
        self.assertEqual(inserted_dup, 0)
        
        # Check group metadata updated
        last_ts = self.db.get_last_seen_ts(12345)
        self.assertEqual(last_ts, "2026-07-03T12:05:00+00:00")


class TestDeduplicator(unittest.TestCase):
    def test_deduplicator(self):
        class MockDB:
            def get_all_hashes(self):
                return {"hash_a", "hash_b"}
        
        db = MockDB()
        dedup = Deduplicator(db)
        
        self.assertTrue(dedup.is_duplicate("hash_a"))
        self.assertFalse(dedup.is_duplicate("hash_c"))
        
        dedup.add("hash_c")
        self.assertTrue(dedup.is_duplicate("hash_c"))


class TestKeywordMatcher(unittest.TestCase):
    def test_keyword_matching(self):
        class MockDB:
            def get_keywords(self):
                return ["crypto scam", "investment opportunity"]
            def get_recent_unmatched_messages(self, limit=1000):
                return []
        
        db = MockDB()
        matcher = KeywordMatcher(db, threshold=85, reload_interval=60)
        
        # Exact match / high similarity
        kw, score = matcher.match("This is a crypto scam watch out!")
        self.assertEqual(kw, "crypto scam")
        self.assertGreaterEqual(score, 85)
        
        # Below threshold for english
        kw, score = matcher.match("Some random chat message")
        self.assertIsNone(kw)
        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
