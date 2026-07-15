import os
import unittest
from src.storage.database import DatabaseHandler, init_db, get_db
from src.processing.reporting_service import compile_intelligence_brief


class TestAnalystReporting(unittest.TestCase):
    def setUp(self):
        self.db_path = "tests/test_reporting_db.db"
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

    def test_watchlist_operations(self):
        # Save watchlist
        params = {"keyword": "weapons", "matched_only": True}
        self.db.save_watchlist("wl_123", "Weapons Monitor", params, "2026-07-04T12:00:00Z")

        # Get watchlists
        wlists = self.db.get_watchlists()
        self.assertEqual(len(wlists), 1)
        self.assertEqual(wlists[0]["name"], "Weapons Monitor")
        self.assertEqual(wlists[0]["query_params"]["keyword"], "weapons")

        # Delete watchlist
        self.db.delete_watchlist("wl_123")
        self.assertEqual(len(self.db.get_watchlists()), 0)

    def test_case_management_and_reporting(self):
        # Create case
        self.db.create_case("case_abc", "Operation Crossfire", "Tracking cross-border funds", "2026-07-04T10:00:00Z")
        
        # Verify case created
        cases = self.db.get_cases()
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["title"], "Operation Crossfire")

        # Add message to case (let's insert a mock message first)
        msg_data = {
            "message_id": 1,
            "group_id": 100,
            "group_name": "Target Group",
            "sender_name": "ActorZ",
            "sender_phone": "918888888888",
            "text": "Send weapons and funds",
            "language": "en",
            "is_forwarded": 0,
            "timestamp": "2026-07-04T11:00:00Z",
            "hash": "msg_hash_val",
            "is_matched": 1,
            "matched_keyword": "weapons",
            "fuzzy_score": 100.0,
            "risk_score": 85.0
        }
        # Insert inside database
        self.db.insert_message(msg_data)
        
        # Resolve inserted row ID
        hash_to_row = self.db.get_message_ids_by_hashes(["msg_hash_val"])
        row_id = hash_to_row.get("msg_hash_val")
        self.assertIsNotNone(row_id)

        # Add case items
        self.db.add_item_to_case("case_abc", "message", str(row_id), "2026-07-04T12:00:00Z")
        self.db.add_item_to_case("case_abc", "wallet", "0xABC123", "2026-07-04T12:05:00Z")
        self.db.add_item_to_case("case_abc", "actor", "ActorZ", "2026-07-04T12:10:00Z")

        # Retrieve case details
        details = self.db.get_case_details("case_abc")
        self.assertIsNotNone(details)
        self.assertEqual(details["title"], "Operation Crossfire")
        self.assertEqual(len(details["items"]), 3)

        # Compile intelligence brief markdown
        report_md = compile_intelligence_brief(details)
        self.assertIn("Operation Crossfire", report_md)
        self.assertIn("CRITICAL", report_md) # risk score 85 should make overall risk Critical
        self.assertIn("Send weapons and funds", report_md)
        self.assertIn("0xABC123", report_md)
        self.assertIn("ActorZ", report_md)

        # Delete case item
        item_id_to_remove = details["items"][0]["id"]
        self.db.remove_item_from_case(item_id_to_remove)
        
        # Verify item count decreased
        updated_details = self.db.get_case_details("case_abc")
        self.assertEqual(len(updated_details["items"]), 2)

        # Delete case
        self.db.delete_case("case_abc")
        self.assertIsNone(self.db.get_case_details("case_abc"))
