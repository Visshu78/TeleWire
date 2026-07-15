import unittest
import os
import shutil
import tempfile
import sqlite3
from datetime import datetime, timezone

from src.storage.database import init_db, DatabaseHandler
from src.processing.entity_extractor import (
    EntityExtractor,
    verify_btc_base58,
    verify_btc_bech32,
    verify_ton_address,
    OFACSanctionChecker
)


class TestEntityExtractor(unittest.TestCase):
    def setUp(self):
        # Create a temp directory for mock OFAC lists
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = EntityExtractor(cache_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_checksum_validators(self):
        # Bitcoin Legacy / P2SH / TRON Base58Check validation
        # Valid BTC Legacy
        self.assertTrue(verify_btc_base58("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")) # Satoshi Genesis Address
        # Invalid BTC Legacy
        self.assertFalse(verify_btc_base58("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb")) # Bad checksum
        
        # Valid TRON Base58Check
        self.assertTrue(verify_btc_base58("T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"))
        # Invalid TRON
        self.assertFalse(verify_btc_base58("T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwc")) # Bad checksum
        
        # Bitcoin Bech32 validation
        # Valid Bech32
        self.assertTrue(verify_btc_bech32("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"))
        # Invalid Bech32
        self.assertFalse(verify_btc_bech32("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5")) # Bad checksum

        # TON validation
        # Valid TON address
        self.assertTrue(verify_ton_address("EQARAIPf1VLmNym0cvy8yMRcJw_xVprTYlyVTyj0Y_ji0my9"))
        # Invalid TON address
        self.assertFalse(verify_ton_address("EQARAIPf1VLmNym0cvy8yMRcJw_xVprTYlyVTyj0Y_ji0my8"))

    def test_regex_extraction(self):
        text = """
        Contact Alice at alice@example.com or @alice_tg. 
        Send payments to alice@okaxis or alice@ybl (not bob@gmail.com).
        India helpline: +91-9876543210 or call 9876543210.
        Visit https://example.com/scam-alert for details.
        Legacy Wallet: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
        Segwit Wallet: bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4
        Tron: T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb
        TON: EQARAIPf1VLmNym0cvy8yMRcJw_xVprTYlyVTyj0Y_ji0my9
        """
        entities = self.extractor.extract(text)
        types = [e["type"] for e in entities]
        
        self.assertIn("email", types)
        self.assertIn("telegram_handle", types)
        self.assertIn("upi_id", types)
        self.assertIn("phone_number", types)
        self.assertIn("url", types)
        self.assertIn("crypto_btc", types)
        self.assertIn("crypto_tron", types)
        self.assertIn("crypto_ton", types)

    def test_ofac_sanction_matching(self):
        # Create a mock sanction file on disk
        sanction_file = os.path.join(self.temp_dir, "sanctioned_addresses_XBT.txt")
        with open(sanction_file, "w", encoding="utf-8") as fh:
            fh.write("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa\n")
            
        checker = OFACSanctionChecker(cache_dir=self.temp_dir)
        checker.load_local_lists()
        
        self.assertTrue(checker.is_sanctioned("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"))
        self.assertFalse(checker.is_sanctioned("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"))


class TestDatabaseEntities(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_entities_db.db")
        init_db(self.db_path)
        self.db = DatabaseHandler(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_entity_saving_and_retrieval(self):
        # Seed group and insert a message
        self.db.upsert_group(999, "Group 999", "group", 5)
        msg = {
            "message_id": 101,
            "group_id": 999,
            "group_name": "Group 999",
            "sender_name": "Alice",
            "sender_phone": None,
            "text": "Call me on +919999999999 or check 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "language": "en",
            "is_forwarded": 0,
            "forward_from_name": None,
            "forward_from_id": None,
            "matched_keyword": None,
            "fuzzy_score": 0.0,
            "is_matched": 0,
            "timestamp": "2026-07-03T15:00:00+00:00",
            "hash": "somehashval"
        }
        
        inserted = self.db.insert_messages_batch([msg])
        self.assertEqual(inserted, 1)
        
        # Get message row ID
        hash_map = self.db.get_message_ids_by_hashes(["somehashval"])
        row_id = hash_map["somehashval"]
        
        # Entities list to insert
        ents = [
            {"type": "phone_number", "value": "+919999999999", "position": 11},
            {"type": "crypto_btc", "value": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "position": 32, "is_sanctioned": 0}
        ]
        
        crypto_enrich = self.db.save_message_entities(row_id, ents, msg["timestamp"])
        
        # Verify returned crypto entities
        self.assertEqual(len(crypto_enrich), 1)
        self.assertEqual(crypto_enrich[0]["value"], "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        
        # Retrieve entities from database and check fields
        saved_ents = self.db.get_message_entities(row_id)
        self.assertEqual(len(saved_ents), 2)
        
        types = [e["entity_type"] for e in saved_ents]
        self.assertIn("phone_number", types)
        self.assertIn("crypto_btc", types)


if __name__ == "__main__":
    unittest.main()
