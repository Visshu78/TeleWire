import os
import time
import logging
from PIL import Image
import pytesseract
import imagehash
try:
    from pyzbar.pyzbar import decode
except Exception as e:
    decode = None

logger = logging.getLogger(__name__)
if decode is None:
    logger.warning("pyzbar DLL dependencies not found on host system. QR code decoding will be bypassed.")

# Configure Tesseract path from env or use standard Windows default
TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if os.path.exists(TESSERACT_CMD):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
else:
    logger.warning("Tesseract OCR binary not found at %s. OCR text extraction will be bypassed.", TESSERACT_CMD)


class MediaProcessor:
    def __init__(self, media_dir: str = "data/media"):
        self.media_dir = media_dir
        os.makedirs(self.media_dir, exist_ok=True)

    def process_image(self, file_path: str) -> dict:
        """
        Extract OCR text, calculate pHash, and decode QR codes from an image.
        Returns a dict: {
            "ocr_text": str,
            "phash": str,
            "qr_codes": list[str]
        }
        """
        results = {
            "ocr_text": "",
            "phash": None,
            "qr_codes": []
        }

        if not os.path.exists(file_path):
            logger.warning("Image file %s does not exist.", file_path)
            return results

        try:
            with Image.open(file_path) as img:
                # 1. Calculate Perceptual Hash (pHash)
                try:
                    p_hash = imagehash.phash(img)
                    results["phash"] = str(p_hash)
                except Exception as exc:
                    logger.error("pHash calculation failed for %s: %s", file_path, exc)

                # 2. Extract OCR Text using Tesseract
                try:
                    # Only execute if binary is configured
                    if os.path.exists(pytesseract.pytesseract.tesseract_cmd):
                        results["ocr_text"] = pytesseract.image_to_string(img).strip()
                except Exception as exc:
                    logger.warning("Tesseract OCR extraction failed for %s: %s", file_path, exc)

                # 3. Decode QR Codes
                try:
                    if decode is not None:
                        decoded_objects = decode(img)
                        for obj in decoded_objects:
                            val = obj.data.decode("utf-8", errors="ignore").strip()
                            if val and val not in results["qr_codes"]:
                                results["qr_codes"].append(val)
                except Exception as exc:
                    logger.warning("QR code decoding failed for %s: %s", file_path, exc)

        except Exception as exc:
            logger.error("Failed to open or parse image %s: %s", file_path, exc)

        return results

    def cleanup_media(self, max_age_days: int = 30, max_size_bytes: int = 5 * 1024 * 1024 * 1024) -> None:
        """
        Purge older media files from disk to prevent storage bloat.
        Maintains DB indexes forever, but deletes old cached files.
        """
        if not os.path.exists(self.media_dir):
            return

        now = time.time()
        age_threshold_sec = max_age_days * 86400
        
        files_info = []
        total_size = 0

        # Gather files details
        for entry in os.scandir(self.media_dir):
            if entry.is_file():
                stat = entry.stat()
                mtime = stat.st_mtime
                size = stat.st_size
                
                # Check 1: Max age filter
                if (now - mtime) > age_threshold_sec:
                    try:
                        os.remove(entry.path)
                        logger.info("Deleted expired media file: %s (age > %d days)", entry.name, max_age_days)
                    except Exception as exc:
                        logger.error("Failed to delete expired file %s: %s", entry.path, exc)
                else:
                    files_info.append({
                        "path": entry.path,
                        "size": size,
                        "mtime": mtime
                    })
                    total_size += size

        # Check 2: Size threshold filter
        if total_size > max_size_bytes:
            # Sort by last modification time (oldest first)
            files_info.sort(key=lambda x: x["mtime"])
            
            for file in files_info:
                if total_size <= max_size_bytes:
                    break
                try:
                    os.remove(file["path"])
                    total_size -= file["size"]
                    logger.info("Deleted media cache overflow file: %s", os.path.basename(file["path"]))
                except Exception as exc:
                    logger.error("Failed to delete overflow file %s: %s", file["path"], exc)
