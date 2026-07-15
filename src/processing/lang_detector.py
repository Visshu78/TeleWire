"""
src/processing/lang_detector.py
────────────────────────────────────────────────────────────
Thin, deterministic wrapper around langdetect.

• DetectorFactory.seed = 0  → reproducible results across runs
• Falls back to "unknown" for texts that are too short, empty,
  or contain only symbols/numbers (common in Telegram messages).
────────────────────────────────────────────────────────────
"""

import logging
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

DetectorFactory.seed = 0          # deterministic

logger = logging.getLogger(__name__)
_MIN_TEXT_LENGTH = 10             # don't try to detect on very short strings


class LanguageDetector:
    def detect(self, text: str) -> str:
        """Return BCP-47 language code or 'unknown'."""
        if not text or len(text.strip()) < _MIN_TEXT_LENGTH:
            return "unknown"
        try:
            return detect(text)
        except LangDetectException:
            return "unknown"
        except Exception as exc:
            logger.debug("lang detection error: %s", exc)
            return "unknown"
