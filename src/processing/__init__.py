"""
src/processing/__init__.py
ProcessingEngine -- combines dedup, language detection, keyword matching, entity extraction.
"""

import hashlib
import logging

from .deduplicator import Deduplicator
from .lang_detector import LanguageDetector
from .keyword_matcher import KeywordMatcher
from .entity_extractor import EntityExtractor
from .wallet_enricher import WalletEnricher
from .semantic_service import SemanticProcessor
from .media_processor import MediaProcessor

logger = logging.getLogger(__name__)


class ProcessingEngine:
    def __init__(self, db_handler, config: dict):
        threshold       = config.get("fuzzy_threshold", 85)
        reload_interval = config.get("keyword_reload_interval", 60)
        self.deduplicator   = Deduplicator(db_handler)
        self.lang_detector  = LanguageDetector()
        self.keyword_matcher = KeywordMatcher(db_handler, threshold, reload_interval)
        self.entity_extractor = EntityExtractor()
        self.wallet_enricher = WalletEnricher(db_handler)
        self.semantic_processor = SemanticProcessor(db_handler)
        self.media_processor = MediaProcessor("data/media")

    @staticmethod
    def make_hash(message_id: int, group_id: int) -> str:
        return hashlib.sha256(f"{message_id}:{group_id}".encode()).hexdigest()

    def process(self, raw: dict) -> dict | None:
        """
        Enrich raw message dict.
        Returns None if duplicate.

        Required keys in raw:
            message_id, group_id, group_name, sender_name, sender_phone,
            text, is_forwarded, forward_from_name, forward_from_id, timestamp
        """
        hash_val = self.make_hash(raw["message_id"], raw["group_id"])
        if self.deduplicator.is_duplicate(hash_val):
            return None

        language = self.lang_detector.detect(raw.get("text", ""))
        matched_keyword, fuzzy_score = self.keyword_matcher.match(raw.get("text", ""), language)
        is_matched = 1 if matched_keyword else 0

        # Extract entities
        entities = self.entity_extractor.extract(raw.get("text", ""))

        return {
            **raw,
            "language":       language,
            "matched_keyword": matched_keyword,
            "fuzzy_score":    round(fuzzy_score, 2),
            "is_matched":     is_matched,
            "hash":           hash_val,
            "entities":       entities,
        }

    def mark_seen(self, hash_val: str) -> None:
        self.deduplicator.add(hash_val)


__all__ = ["ProcessingEngine"]
