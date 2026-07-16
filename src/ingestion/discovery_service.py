"""
src/ingestion/discovery_service.py
-------------------------------------------------------------
Group Discovery Scanner -- runs as a background asyncio task.

Two scan methods per cycle (default: every 300 seconds):
  1. Keyword Search  -- contacts.SearchRequest for each threat keyword.
  2. Invite Link     -- regex scan of recently ingested messages for
                       t.me/+ invite-link hashes.

Newly discovered groups land in pending_groups (status='pending')
for analyst approval before any auto-join happens.
-------------------------------------------------------------
"""

import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Regex to extract invite hashes from t.me/+HASH or t.me/joinchat/HASH
_INVITE_RE = re.compile(
    r"(?:https?://)?t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]{10,})",
    re.IGNORECASE,
)


class GroupDiscoveryService:
    """
    Periodic background scanner for new Telegram groups.

    Parameters
    ----------
    client        : Telethon TelegramClient (already authenticated)
    db            : DatabaseHandler instance
    scan_interval : seconds between full scan cycles (default 300 = 5 min)
    """

    def __init__(self, client, db, scan_interval: int = 300):
        self.client = client
        self.db = db
        self.scan_interval = scan_interval
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop -- scan -> sleep -> repeat until cancelled."""
        self._running = True
        logger.info(
            "GroupDiscoveryService started (interval=%ds)", self.scan_interval
        )
        while self._running:
            try:
                await self._scan_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Discovery scan cycle error: %s", exc)
            try:
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                break
        logger.info("GroupDiscoveryService stopped.")

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Scan cycle
    # ------------------------------------------------------------------

    async def _scan_cycle(self) -> None:
        logger.info("Discovery scan cycle starting...")
        kw_found = await self._scan_by_keywords()
        inv_found = await self._scan_invite_links()
        total = kw_found + inv_found
        if total:
            logger.info(
                "Discovery scan: %d new pending groups (%d keyword, %d invite-link)",
                total, kw_found, inv_found,
            )
        else:
            logger.debug("Discovery scan: no new groups found this cycle.")

    # ------------------------------------------------------------------
    # Method 1 -- Keyword-based public group search
    # ------------------------------------------------------------------

    async def _scan_by_keywords(self) -> int:
        """
        Search Telegram public index for each threat keyword.
        Adds any unknown result to pending_groups.
        Returns count of newly queued groups.
        """
        from telethon.tl.functions.contacts import SearchRequest
        from telethon.errors import FloodWaitError

        keywords = self.db.get_keywords()
        if not keywords:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        new_count = 0

        for kw in keywords:
            try:
                result = await self.client(
                    SearchRequest(q=kw, limit=50)
                )
                await asyncio.sleep(2)  # polite delay between keyword requests

                for chat in getattr(result, "chats", []):
                    gid = getattr(chat, "id", None)
                    gname = getattr(chat, "title", "") or ""
                    gusername = getattr(chat, "username", None)
                    members = getattr(chat, "participants_count", 0) or 0

                    if not gname:
                        continue
                    if self.db.is_group_known(gid, gname, None):
                        continue

                    saved = self.db.save_pending_group(
                        group_id=gid,
                        group_name=gname,
                        group_username=gusername,
                        member_count=members,
                        invite_link=None,
                        source="keyword_search",
                        source_keyword=kw,
                        discovered_at=now,
                    )
                    if saved:
                        new_count += 1
                        logger.info(
                            "Discovery [keyword=%r]: queued group %r (id=%s, members=%d)",
                            kw, gname, gid, members,
                        )

            except FloodWaitError as exc:
                wait = exc.seconds + 5
                logger.warning(
                    "FloodWait during keyword scan, sleeping %ds", wait
                )
                await asyncio.sleep(wait)
            except Exception as exc:
                logger.warning("Keyword scan error for %r: %s", kw, exc)

        return new_count

    # ------------------------------------------------------------------
    # Method 2 -- Invite-link extraction from recent messages
    # ------------------------------------------------------------------

    async def _scan_invite_links(self) -> int:
        """
        Query messages from the last 15 minutes and extract t.me/+ hashes.
        Unknown links are queued for analyst review.
        Returns count of newly queued links.
        """
        from telethon.errors import (
            FloodWaitError,
            InviteHashExpiredError,
            InviteHashInvalidError,
            UserAlreadyParticipantError,
        )

        try:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(minutes=15)
            ).isoformat()

            recent = self.db.get_messages(
                datetime_from=cutoff,
                page_size=500,
            )
            texts = [m.get("text", "") or "" for m in recent.get("messages", [])]
        except Exception as exc:
            logger.warning("Invite-link scan: failed to fetch messages: %s", exc)
            return 0

        now = datetime.now(timezone.utc).isoformat()
        new_count = 0
        seen_hashes: set = set()

        for text in texts:
            for match in _INVITE_RE.finditer(text):
                invite_hash = match.group(1)
                full_link = f"https://t.me/+{invite_hash}"

                if invite_hash in seen_hashes:
                    continue
                seen_hashes.add(invite_hash)

                if self.db.is_group_known(None, None, full_link):
                    continue

                # Save immediately with hash as placeholder name
                group_name = f"invite:{invite_hash[:8]}..."
                gid = None
                members = 0

                saved = self.db.save_pending_group(
                    group_id=gid,
                    group_name=group_name,
                    group_username=None,
                    member_count=members,
                    invite_link=full_link,
                    source="invite_link",
                    source_keyword=None,
                    discovered_at=now,
                )
                if saved:
                    new_count += 1
                    logger.info(
                        "Discovery [invite-link]: queued link %s", full_link
                    )

        return new_count
