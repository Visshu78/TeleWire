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


if __name__ == "__main__":
    unittest.main()
