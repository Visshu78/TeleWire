import unittest
import os
import shutil
import tempfile
import json
import faiss

from src.storage.database import init_db, DatabaseHandler
from src.processing.semantic_service import SemanticProcessor, THREAT_CATEGORIES


class TestSemanticIntelligence(unittest.TestCase):
    def setUp(self):
        SemanticProcessor._instance = None
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_semantics_db.db")
        init_db(self.db_path)
        self.db = DatabaseHandler(self.db_path)
        
        # Override file paths for FAISS to keep tests sandboxed inside temp dir
        self.index_path = os.path.join(self.test_dir, "faiss_index.bin")
        self.mapping_path = os.path.join(self.test_dir, "faiss_mapping.json")
        
        # Patch paths inside the semantic_service module
        import src.processing.semantic_service as ss
        self.old_index_path = ss.INDEX_PATH
        self.old_mapping_path = ss.MAPPING_PATH
        ss.INDEX_PATH = self.index_path
        ss.MAPPING_PATH = self.mapping_path
        
        # Initialize processor
        self.processor = SemanticProcessor(self.db)

    def tearDown(self):
        # Restore patched paths
        import src.processing.semantic_service as ss
        ss.INDEX_PATH = self.old_index_path
        ss.MAPPING_PATH = self.old_mapping_path
        SemanticProcessor._instance = None
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_zero_shot_classification(self):
        # Cybersecurity/Hacking
        cat_cyber = self.processor.classify_zero_shot("Looking for professional hackers to break into database, exploit SQL injection")
        self.assertEqual(cat_cyber, "Cybersecurity/Hacking")

        # Drug Trafficking
        cat_drugs = self.processor.classify_zero_shot("selling high grade weed, cocaine, pills, fast shipping telegram contact")
        self.assertEqual(cat_drugs, "Drug Trafficking")

        # Scam/Fraud
        cat_scam = self.processor.classify_zero_shot("Send 100 USDT to receive 200 USDT reward bonus immediately double your money")
        self.assertEqual(cat_scam, "Scam/Fraud")

        # Legitimate/Other
        cat_other = self.processor.classify_zero_shot("Hey guys, what time does the grocery shop close tonight?")
        self.assertEqual(cat_other, "Other/Legitimate")

    def test_near_duplicate_campaign_clustering(self):
        # Seed groups
        self.db.upsert_group(801, "Ingested Group Alpha", "supergroup", 50)
        
        msg_1_text = "Send 100 USDT to receive 200 USDT reward bonus immediately and double your money right now!"
        msg_2_text = "Send 100 USDT to get 200 USDT bonus payout immediately and double your funds right away!"
        msg_3_text = "We are selling high quality military weapons, handguns, explosives. Contact us for bulk orders." # different campaign
        
        timestamp = "2026-07-03T12:00:00+00:00"
        
        # Insert first message to generate row ID
        msg_data_1 = {
            "message_id": 1001,
            "group_id": 801,
            "group_name": "Ingested Group Alpha",
            "sender_name": "Scammer A",
            "sender_phone": None,
            "text": msg_1_text,
            "language": "en",
            "is_forwarded": 0,
            "forward_from_name": None,
            "forward_from_id": None,
            "matched_keyword": "USDT",
            "fuzzy_score": 100.0,
            "is_matched": 1,
            "timestamp": timestamp,
            "hash": "hash_msg_1"
        }
        self.db.insert_message(msg_data_1)
        
        # Get row ID
        row_id_1 = self.db.get_message_ids_by_hashes(["hash_msg_1"])["hash_msg_1"]
        
        # Process message 1 semantics
        camp_id_1, cat_1 = self.processor.process_message_semantics(row_id_1, msg_1_text, timestamp)
        self.assertTrue(camp_id_1.startswith("camp_"))
        self.assertEqual(cat_1, "Scam/Fraud")
        
        # Insert second message (near duplicate)
        msg_data_2 = msg_data_1.copy()
        msg_data_2.update({"message_id": 1002, "text": msg_2_text, "hash": "hash_msg_2"})
        self.db.insert_message(msg_data_2)
        row_id_2 = self.db.get_message_ids_by_hashes(["hash_msg_2"])["hash_msg_2"]
        
        # Process message 2 semantics
        camp_id_2, cat_2 = self.processor.process_message_semantics(row_id_2, msg_2_text, timestamp)
        # Should cluster to the SAME campaign
        self.assertEqual(camp_id_1, camp_id_2)
        self.assertEqual(cat_2, "Scam/Fraud")
        
        # Insert third message (different campaign topic)
        msg_data_3 = msg_data_1.copy()
        msg_data_3.update({"message_id": 1003, "text": msg_3_text, "hash": "hash_msg_3"})
        self.db.insert_message(msg_data_3)
        row_id_3 = self.db.get_message_ids_by_hashes(["hash_msg_3"])["hash_msg_3"]
        
        # Process message 3 semantics
        camp_id_3, cat_3 = self.processor.process_message_semantics(row_id_3, msg_3_text, timestamp)
        # Should cluster to a NEW campaign
        self.assertNotEqual(camp_id_1, camp_id_3)
        self.assertEqual(cat_3, "Weapons/Violent Extremism")

    def test_faiss_index_persistence(self):
        # Seed an item and save
        self.processor.index_to_msg_id = [9999]
        # create a dummy query vector and add it
        import numpy as np
        vec = np.zeros((1, 384), dtype=np.float32)
        vec[0][0] = 1.0
        self.processor.index.add(vec)
        self.processor._save_index()
        
        # Confirm files were created
        self.assertTrue(os.path.exists(self.index_path))
        self.assertTrue(os.path.exists(self.mapping_path))
        
        # Re-initialize processor and load
        new_processor = SemanticProcessor(self.db)
        self.assertEqual(new_processor.index.ntotal, 1)
        self.assertEqual(new_processor.index_to_msg_id, [9999])


if __name__ == "__main__":
    unittest.main()
