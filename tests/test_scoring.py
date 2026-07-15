import os
import unittest
from unittest.mock import patch, MagicMock

from src.storage.database import DatabaseHandler, init_db, get_db
from src.processing.scoring_service import calculate_risk_score, dispatch_alerts


class TestThreatScoring(unittest.TestCase):
    def setUp(self):
        self.db_path = "tests/test_scoring_db.db"
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

    def test_calculate_risk_score(self):
        # Case 1: Simple Benign message (no hits)
        msg1 = {
            "text": "Hello, how are you?",
            "threat_category": "Benign",
            "is_matched": 0,
            "entities": []
        }
        self.assertEqual(calculate_risk_score(msg1), 0.0)

        # Case 2: Sanctioned wallet + urgency term
        msg2 = {
            "text": "Hurry up! Send BTC immediately!",
            "threat_category": "Benign",
            "is_matched": 0,
            "entities": [{"is_sanctioned": 1}]
        }
        # 40 (sanctioned wallet) + 10 (urgency) = 50
        self.assertEqual(calculate_risk_score(msg2), 50.0)

        # Case 3: Weapons category + keyword match + campaign
        msg3 = {
            "text": "Selling military weapons right now",
            "threat_category": "Weapons/Violent Extremism",
            "is_matched": 1,
            "fuzzy_score": 100.0,
            "campaign_id": "camp_abc"
        }
        # 30 (Weapons) + 15 (100% fuzzy) + 10 (campaign) + 10 (urgency: right now) = 65
        self.assertEqual(calculate_risk_score(msg3), 65.0)

    def test_sender_profile_aggregation(self):
        # Update profile for same sender twice
        self.db.update_sender_profile("ScammerX", None, 50.0, "2026-07-03T12:00:00Z")
        self.db.update_sender_profile("ScammerX", "919999999999", 90.0, "2026-07-03T13:00:00Z")

        # Query profile
        with get_db(self.db_path) as conn:
            profile = conn.execute("SELECT * FROM sender_profiles WHERE sender_id = ?", ("ScammerX",)).fetchone()
            self.assertIsNotNone(profile)
            self.assertEqual(profile["total_messages"], 2)
            self.assertEqual(profile["cumulative_risk"], 140.0)
            self.assertEqual(profile["average_risk"], 70.0)
            self.assertEqual(profile["risk_tier"], "High") # Average 70 is High tier

        # Create another profile
        self.db.update_sender_profile("MuleY", None, 95.0, "2026-07-03T14:00:00Z") # Average 95 is Critical tier
        
        # Verify sorting
        actors = self.db.get_high_risk_actors(limit=5)
        self.assertEqual(len(actors), 2)
        self.assertEqual(actors[0]["sender_id"], "ScammerX") # 140 cumulative risk > 95 cumulative risk
        self.assertEqual(actors[1]["sender_id"], "MuleY")

    @patch("src.processing.scoring_service.requests.post")
    def test_alert_dispatcher(self, mock_post):
        # Set threshold env variable
        os.environ["ALERT_THRESHOLD"] = "80"
        os.environ["ALERT_WEBHOOK_URL"] = "https://mywebhook.com/alert"
        os.environ["ALERT_TELEGRAM_BOT_TOKEN"] = "token123"
        os.environ["ALERT_TELEGRAM_CHAT_ID"] = "chat123"

        msg = {
            "message_id": 999,
            "group_name": "Scam Channel",
            "text": "CRITICAL WEAPONS TRADING"
        }

        # Below threshold (75 < 80) -> no alert
        dispatch_alerts(msg, 75.0)
        self.assertFalse(mock_post.called)

        # Above threshold (85 >= 80) -> dispatch alert
        dispatch_alerts(msg, 85.0)
        self.assertTrue(mock_post.called)
        self.assertEqual(mock_post.call_count, 2) # 1 webhook + 1 Telegram message
