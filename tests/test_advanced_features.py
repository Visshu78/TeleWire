import os
import unittest
from src.storage.database import DatabaseHandler, init_db
from src.processing.reporting_service import generate_inline_diff, generate_ai_brief
from src.processing.semantic_service import SemanticProcessor


class TestAdvancedFeatures(unittest.TestCase):
    def setUp(self):
        self.db_path = "tests/test_advanced_features_db.db"
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass
        init_db(self.db_path)
        self.db = DatabaseHandler(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_inline_diff_generator(self):
        text1 = "Selling military rifles and ammunition now"
        text2 = "Selling military rifles and weapons right now"
        
        diff_html = generate_inline_diff(text1, text2)
        self.assertIn("rifles", diff_html)
        self.assertIn("line-through", diff_html) # deletion
        self.assertIn("#4ade80", diff_html) # insertion green highlight

    def test_ai_brief_generator(self):
        case_details = {
            "title": "Crypto Scam Network Op",
            "description": "Investigating coordinated crypto doubling scam",
            "created_at": "2026-07-20T10:00:00Z",
            "items": [
                {
                    "item_type": "message",
                    "message_details": {
                        "timestamp": "2026-07-20T11:00:00Z",
                        "sender_name": "Scammer1",
                        "group_name": "ScamGroup",
                        "text": "Send BTC to double money",
                        "threat_category": "Scam/Fraud",
                        "risk_score": 85.0
                    }
                },
                {"item_type": "wallet", "item_value": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"},
                {"item_type": "actor", "item_value": "@scammer_tg"}
            ]
        }
        
        brief = generate_ai_brief(case_details)
        self.assertIn("Crypto Scam Network Op", brief)
        self.assertIn("Scam/Fraud", brief)
        self.assertIn("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", brief)

    def test_semantic_similar_messages_search(self):
        proc = SemanticProcessor(db_handler=self.db)
        # Empty text search returns empty list
        self.assertEqual(proc.search_similar_messages(""), [])

    def test_stix_bundle_builder(self):
        from src.processing.reporting_service import generate_stix_bundle
        case_details = {
            "title": "Operation Alpha",
            "description": "Scam group monitoring",
            "items": [
                {
                    "item_type": "message",
                    "message_details": {
                        "id": 1,
                        "timestamp": "2026-07-20T11:00:00Z",
                        "sender_name": "ActorA",
                        "group_name": "Channel1",
                        "text": "Send crypto to address 1A1zP"
                    }
                },
                {"item_type": "wallet", "item_value": "1A1zP"},
                {"item_type": "actor", "item_value": "ActorA"}
            ]
        }
        bundle = generate_stix_bundle(case_details)
        self.assertEqual(bundle["type"], "bundle")
        self.assertTrue(len(bundle["objects"]) > 0)
        
        # Verify identity is present
        identities = [o for o in bundle["objects"] if o["type"] == "identity"]
        self.assertEqual(len(identities), 1)
        self.assertEqual(identities[0]["name"], "TeleWire SOCMINT Threat Intelligence Platform")

        # Verify threat actor is present
        actors = [o for o in bundle["objects"] if o["type"] == "threat-actor"]
        self.assertEqual(len(actors), 1)
        self.assertEqual(actors[0]["name"], "ActorA")

        # Verify wallet indicator is present
        indicators = [o for o in bundle["objects"] if o["type"] == "indicator"]
        self.assertEqual(len(indicators), 1)
        self.assertIn("1A1zP", indicators[0]["pattern"])

        # Verify note is present
        notes = [o for o in bundle["objects"] if o["type"] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIn("Sender: ActorA", notes[0]["content"])

    def test_propagation_timeline(self):
        # Insert duplicate text messages with different timestamps and unique hashes, linked via campaign_id
        from src.storage.database import get_db
        with get_db(self.db_path) as conn:
            conn.execute('''
                INSERT INTO messages (message_id, group_id, group_name, sender_name, timestamp, text, hash, campaign_id, risk_score)
                VALUES (1, 101, "Group 1", "Sender A", "2026-07-22T10:00:00Z", "Identical broadcast message", "hash1", "camp123", 50.0)
            ''')
            conn.execute('''
                INSERT INTO messages (message_id, group_id, group_name, sender_name, timestamp, text, hash, campaign_id, risk_score)
                VALUES (2, 102, "Group 2", "Sender B", "2026-07-22T10:05:00Z", "Identical broadcast message", "hash2", "camp123", 50.0)
            ''')
            conn.execute('''
                INSERT INTO messages (message_id, group_id, group_name, sender_name, timestamp, text, hash, campaign_id, risk_score)
                VALUES (3, 103, "Group 3", "Sender C", "2026-07-22T11:00:00Z", "Identical broadcast message", "hash3", "camp123", 50.0)
            ''')
            
        # Verify propagation endpoint logic matches
        msg = self.db.get_message_by_row_id(1)
        self.assertIsNotNone(msg)
        
        # Test propagation query manually
        with get_db(self.db_path) as conn:
            rows = conn.execute('''
                SELECT id, group_name, sender_name, timestamp, text, risk_score
                FROM messages
                WHERE campaign_id = "camp123"
                ORDER BY timestamp ASC
            ''').fetchall()
            
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["sender_name"], "Sender A")
        self.assertEqual(rows[1]["sender_name"], "Sender B")
        self.assertEqual(rows[2]["sender_name"], "Sender C")



if __name__ == "__main__":
    unittest.main()
