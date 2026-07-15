"""
src/processing/deduplicator.py
────────────────────────────────────────────────────────────
Thread-safe in-memory hash store.

On startup it loads ALL existing SHA-256 hashes from the DB so the
set survives restarts.  The asyncio listener calls add() after each
successful insert; Flask reads never touch this object.
────────────────────────────────────────────────────────────
"""

import threading
import logging
from typing import Set

logger = logging.getLogger(__name__)


class Deduplicator:
    def __init__(self, db_handler):
        self._lock = threading.Lock()
        self._hashes: Set[str] = set()
        self._warm_up(db_handler)

    def _warm_up(self, db_handler) -> None:
        hashes = db_handler.get_all_hashes()
        with self._lock:
            self._hashes = hashes
        logger.info("Deduplicator warmed up with %d known hashes", len(hashes))

    def is_duplicate(self, hash_val: str) -> bool:
        with self._lock:
            return hash_val in self._hashes

    def add(self, hash_val: str) -> None:
        with self._lock:
            self._hashes.add(hash_val)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._hashes)
