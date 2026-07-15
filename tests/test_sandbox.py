import os
import unittest
from scripts.generate_mock_stream import generate_mock_message, MOCK_GROUPS, MOCK_SENDERS
from src.storage.database import DatabaseHandler, init_db, get_db
from src.processing import ProcessingEngine


class TestSandboxMockStream(unittest.TestCase):
    def setUp(self):
        self.db_path = "tests/test_sandbox_db.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        init_db(self.db_path)
        self.db = DatabaseHandler(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_generate_mock_message(self):
        raw = generate_mock_message(42)
        self.assertEqual(raw["message_id"], 42)
        self.assertIn(raw["group_name"], [g["name"] for g in MOCK_GROUPS])
        self.assertIn(raw["sender_name"], [s["name"] for s in MOCK_SENDERS])
        self.assertIsNotNone(raw["text"])
        self.assertIsNotNone(raw["timestamp"])

    def test_mock_ingestion_simulation(self):
        # Setup groups
        for g in MOCK_GROUPS:
            self.db.upsert_group(g["id"], g["name"], g["type"], member_count=100)

        engine = ProcessingEngine(self.db, {"fuzzy_threshold": 80})

        # Insert 3 mock messages and verify database count
        for i in range(1, 4):
            raw = generate_mock_message(100 + i)
            enriched = engine.process(raw)
            self.assertIsNotNone(enriched)
            
            inserted = self.db.insert_message(enriched)
            self.assertTrue(inserted)

        # Query database directly to count messages
        with get_db(self.db_path) as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            self.assertEqual(cnt, 3)
