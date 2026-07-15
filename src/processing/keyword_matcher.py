"""
src/processing/keyword_matcher.py
────────────────────────────────────────────────────────────
rapidfuzz-based fuzzy keyword matcher.

Strategy:
  • For every keyword K, compute fuzz.partial_ratio(K, message_text).
    partial_ratio checks if K appears as a contiguous substring, so a
    short keyword like "scam" found inside a long message scores 100.
  • Return the best (keyword, score) pair above the configured threshold.
  • Reloads keyword list from DB every `reload_interval` seconds so that
    keywords added via Streamlit or the dashboard take effect live.
────────────────────────────────────────────────────────────
"""

import time
import logging
import threading
from typing import Optional, Tuple

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


class KeywordMatcher:
    def __init__(self, db_handler, threshold: int = 85, reload_interval: int = 60):
        self.db_handler = db_handler
        self.threshold = threshold
        self.reload_interval = reload_interval
        self._keywords: list = []
        self._last_reload: float = 0.0
        self._lock = threading.Lock()
        self.reload()

    # ── Public API ────────────────────────────────────────────────────────────

    def match(self, text: str, language: str = 'en') -> Tuple[Optional[str], float]:
        """
        Returns (matched_keyword, score) or (None, 0.0).
        Auto-reloads keywords if the reload interval has elapsed.
        """
        self._maybe_reload()
        if not text or not self._keywords:
            return None, 0.0

        text_lower = text.lower()
        best_keyword: Optional[str] = None
        best_score: float = 0.0
        
        threshold = self.threshold
        if language != 'en':
            threshold = 72

        with self._lock:
            keywords_snapshot = list(self._keywords)

        for kw in keywords_snapshot:
            score = fuzz.partial_ratio(kw.lower(), text_lower)
            if score >= threshold and score > best_score:
                best_score = score
                best_keyword = kw

        return best_keyword, best_score

    def reload(self) -> None:
        """Force a reload of keywords from the database."""
        keywords = self.db_handler.get_keywords()
        old_keywords = getattr(self, '_keywords', [])
        new_added = set(keywords) - set(old_keywords)
        
        with self._lock:
            self._keywords = keywords
            self._last_reload = time.monotonic()
        logger.debug("KeywordMatcher: loaded %d keywords", len(keywords))
        
        if new_added and old_keywords:
            threading.Thread(target=self._retroactive_match, args=(list(new_added),)).start()

    def _retroactive_match(self, new_keywords: list) -> None:
        logger.info("Retroactive matching against %d new keywords...", len(new_keywords))
        messages = self.db_handler.get_recent_unmatched_messages(limit=1000)
        matched = 0
        for msg in messages:
            text = (msg.get("text") or "").lower()
            if not text:
                continue
            
            best_kw = None
            best_score = 0.0
            
            threshold = self.threshold
            if msg.get("language") != "en":
                threshold = 72
                
            for kw in new_keywords:
                score = fuzz.partial_ratio(kw.lower(), text)
                if score >= threshold and score > best_score:
                    best_score = score
                    best_kw = kw
                    
            if best_kw:
                self.db_handler.update_message_match(msg["id"], best_kw, round(best_score, 2))
                matched += 1
                
        if matched:
            logger.info("Retroactive match found %d messages for new keywords.", matched)

    def add_keywords(self, keywords: list) -> None:
        """Add a batch of keywords to the DB and reload in-memory list."""
        for kw in keywords:
            self.db_handler.add_keyword(kw)
        self.reload()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _maybe_reload(self) -> None:
        if time.monotonic() - self._last_reload > self.reload_interval:
            self.reload()
