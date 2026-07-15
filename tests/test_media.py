import os
import shutil
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image, ImageDraw
import imagehash
import json

from src.storage.database import DatabaseHandler, init_db, get_db
from src.processing.media_processor import MediaProcessor


class TestMediaIngestion(unittest.TestCase):
    def setUp(self):
        # Create temp media folder
        self.test_media_dir = "tests/test_media_dir"
        os.makedirs(self.test_media_dir, exist_ok=True)
        self.processor = MediaProcessor(media_dir=self.test_media_dir)
        
        # Temp database for testing
        self.db_path = "tests/test_media_db.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        init_db(self.db_path)
        self.db = DatabaseHandler(self.db_path)

    def tearDown(self):
        # Clean up temp media folder
        if os.path.exists(self.test_media_dir):
            shutil.rmtree(self.test_media_dir)
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_phash_similar_images(self):
        # Create a basic image
        img1 = Image.new("RGB", (200, 100), color=(73, 109, 137))
        d1 = ImageDraw.Draw(img1)
        d1.text((10, 10), "Threat Alert", fill=(255, 255, 0))
        
        # Create a slightly shifted image (visually similar)
        img2 = Image.new("RGB", (200, 100), color=(73, 109, 137))
        d2 = ImageDraw.Draw(img2)
        d2.text((12, 10), "Threat Alert", fill=(255, 255, 0)) # minor shift
        
        # Calculate pHashes
        h1 = imagehash.phash(img1)
        h2 = imagehash.phash(img2)
        
        distance = h1 - h2
        self.assertLessEqual(distance, 4, "Slightly shifted images should have low pHash distance")

    @patch("src.processing.media_processor.decode")
    @patch("src.processing.media_processor.pytesseract.image_to_string")
    def test_media_processor_extraction(self, mock_ocr, mock_qr_decode):
        # Setup mocks
        mock_ocr.return_value = "Send money to unlock package\n"
        
        mock_qr_obj = MagicMock()
        mock_qr_obj.data = b"https://scamlink.com/payment"
        mock_qr_decode.return_value = [mock_qr_obj]
        
        # Write dummy image file
        img_path = os.path.join(self.test_media_dir, "dummy.jpg")
        img = Image.new("RGB", (100, 100), color="blue")
        img.save(img_path)
        
        # Override Tesseract path to point to a valid file so the check passes
        import pytesseract
        old_cmd = pytesseract.pytesseract.tesseract_cmd
        pytesseract.pytesseract.tesseract_cmd = img_path
        
        try:
            res = self.processor.process_image(img_path)
        finally:
            pytesseract.pytesseract.tesseract_cmd = old_cmd
        
        self.assertEqual(res["ocr_text"], "Send money to unlock package")
        self.assertEqual(res["qr_codes"], ["https://scamlink.com/payment"])
        self.assertIsNotNone(res["phash"])

    def test_database_media_info_update_and_similarity(self):
        # Insert a target message
        hash_val = "12345678"
        self.db.upsert_group(901, "Target Group", "supergroup", 10)
        
        msg_data_1 = {
            "message_id": 2001,
            "group_id": 901,
            "group_name": "Target Group",
            "sender_name": "Sender 1",
            "sender_phone": None,
            "text": "Send funds now",
            "language": "en",
            "is_forwarded": 0,
            "forward_from_name": None,
            "forward_from_id": None,
            "matched_keyword": "funds",
            "fuzzy_score": 100.0,
            "is_matched": 1,
            "timestamp": "2026-07-03T12:00:00+00:00",
            "hash": "hash_msg_1"
        }
        self.db.insert_message(msg_data_1)
        row_id_1 = self.db.get_message_ids_by_hashes(["hash_msg_1"])["hash_msg_1"]
        
        # Populate media metrics
        dummy_phash = str(imagehash.phash(Image.new("RGB", (50, 50), color="red")))
        self.db.update_message_media_info(
            row_id_1,
            media_path="data/media/img_901_2001.jpg",
            ocr_text="DUMMY OCR TEXT",
            phash=dummy_phash,
            qr_codes=["upi://pay?pa=scam@upi"]
        )
        
        # Retrieve message and assert fields
        with get_db(self.db.db_path) as conn:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (row_id_1,)).fetchone()
            self.assertEqual(row["media_path"], "data/media/img_901_2001.jpg")
            self.assertEqual(row["ocr_text"], "DUMMY OCR TEXT")
            self.assertEqual(row["phash"], dummy_phash)
            self.assertEqual(json.loads(row["qr_codes"]), ["upi://pay?pa=scam@upi"])

        # Query similar images
        sims = self.db.get_similar_images(dummy_phash, max_distance=2)
        self.assertEqual(len(sims), 1)
        self.assertEqual(sims[0]["id"], row_id_1)
        self.assertEqual(sims[0]["distance"], 0)

    def test_media_cleanup(self):
        # Create multiple dummy files
        for i in range(5):
            path = os.path.join(self.test_media_dir, f"file_{i}.jpg")
            with open(path, "w") as f:
                f.write("A" * 1000) # 1KB dummy size
                
        # Assert 5 files exist
        self.assertEqual(len(os.listdir(self.test_media_dir)), 5)
        
        # Run cleanup with size limit under 2KB (so max 2 files of 1KB remain)
        self.processor.cleanup_media(max_age_days=30, max_size_bytes=2500)
        
        # Assert oldest files deleted and only 2 remaining
        self.assertEqual(len(os.listdir(self.test_media_dir)), 2)
