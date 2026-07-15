import os
import unittest
import asyncio
from src.storage.database import DatabaseHandler, init_db, get_db
from src.ingestion.pipeline_manager import PipelineManager
from src.processing import ProcessingEngine


class TestMultiAccountIngestion(unittest.TestCase):
    def setUp(self):
        self.db_path = "tests/test_multi_account_db.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        init_db(self.db_path)
        self.db = DatabaseHandler(self.db_path)
        self.engine = ProcessingEngine(self.db, {"fuzzy_threshold": 80})
        self.config = {
            "backup_dir": "tests/test_backup",
            "backup_enabled": False
        }

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_database_crud_methods(self):
        # 1. Initially empty
        accounts = self.db.get_telegram_accounts()
        self.assertEqual(len(accounts), 0)

        # 2. Add first account
        success = self.db.upsert_telegram_account(
            phone="+919876543210",
            api_id=111111,
            api_hash="hash1",
            session_name="data/session1",
            is_active=1,
            status="disconnected"
        )
        self.assertTrue(success)

        # 3. Add second account
        success = self.db.upsert_telegram_account(
            phone="+919999988888",
            api_id=222222,
            api_hash="hash2",
            session_name="data/session2",
            is_active=1,
            status="needs_otp"
        )
        self.assertTrue(success)

        # Verify get_telegram_accounts returns exactly 2
        accounts = self.db.get_telegram_accounts()
        self.assertEqual(len(accounts), 2)
        phones = [acc["phone"] for acc in accounts]
        self.assertIn("+919876543210", phones)
        self.assertIn("+919999988888", phones)

        # 4. Update status
        self.db.update_telegram_account_status("+919876543210", "connected")
        accounts = self.db.get_telegram_accounts()
        acc1 = next(a for a in accounts if a["phone"] == "+919876543210")
        self.assertEqual(acc1["status"], "connected")

        # 5. Delete account
        self.db.delete_telegram_account("+919999988888")
        accounts = self.db.get_telegram_accounts()
        self.assertEqual(len(accounts), 1)

    def test_pipeline_manager_status_logic(self):
        # Seed accounts
        self.db.upsert_telegram_account("+919876543210", 111111, "hash1", "data/session1")
        self.db.upsert_telegram_account("+919999988888", 222222, "hash2", "data/session2")

        manager = PipelineManager(self.db, self.engine, self.config)
        status = manager.get_status()

        # Check fields
        self.assertTrue(status["is_fetching"])
        self.assertEqual(len(status["accounts"]), 2)

        # Check OTP caching injection simulation
        manager.pending_otps["+919999988888"] = {"dummy_client": True}
        updated_status = manager.get_status()
        acc2 = next(a for a in updated_status["accounts"] if a["phone"] == "+919999988888")
        self.assertEqual(acc2["status"], "needs_otp")

    def test_pipeline_manager_toggle_active_method(self):
        self.db.upsert_telegram_account("+919876543210", 111111, "hash1", "data/session1")
        manager = PipelineManager(self.db, self.engine, self.config)
        
        # Deactivate
        res = asyncio.run(manager.toggle_account_active("+919876543210", 0))
        self.assertEqual(res["status"], "disconnected")
        accounts = self.db.get_telegram_accounts()
        acc = next(a for a in accounts if a["phone"] == "+919876543210")
        self.assertEqual(acc["is_active"], 0)

