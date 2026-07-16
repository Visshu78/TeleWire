"""
src/ingestion/listener.py
-------------------------------------------------------------
Real-time Telethon event listener.

Design:
  - events.NewMessage() on ALL chats; active-group gate via in-memory cache.
  - FloodWaitError  -> sleep(exc.seconds), no crash.
  - Exception types are specific; KeyboardInterrupt is explicitly re-raised.
  - fwd_from ground-truth: message.fwd_from gives the real original source
    channel/group. Stored as forward_from_name + forward_from_id.
    is_forwarded=1 whenever forward is set, even without fwd_from details.
  - Raw messages written to JSONL backup.
-------------------------------------------------------------
"""

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone

from telethon import events
from telethon.errors import (
    ChannelPrivateError,
    ChatForbiddenError,
    FloodWaitError,
    RPCError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Active-group in-memory cache
# ---------------------------------------------------------------------------

class ActiveGroupCache:
    """
    In-memory set of active group_ids.
    Flask routes call set_active() after DB toggle so the listener sees the
    change on the very next message — zero DB reads per message.
    """

    def __init__(self, db_handler):
        self._lock = threading.Lock()
        self._active: set = set(db_handler.get_active_group_ids())
        logger.info("ActiveGroupCache: %d groups initially active", len(self._active))

    def is_active(self, group_id: int) -> bool:
        with self._lock:
            return group_id in self._active

    def set_active(self, group_id: int, state: bool) -> None:
        with self._lock:
            if state:
                self._active.add(group_id)
            else:
                self._active.discard(group_id)

    def add(self, group_id: int) -> None:
        with self._lock:
            self._active.add(group_id)


# ---------------------------------------------------------------------------
# Backup writer
# ---------------------------------------------------------------------------

class BackupWriter:
    def __init__(self, backup_dir: str, enabled: bool = True):
        self.enabled = enabled
        self.backup_dir = backup_dir
        if enabled:
            os.makedirs(backup_dir, exist_ok=True)

    def write(self, data: dict) -> None:
        if not self.enabled:
            return
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filepath = os.path.join(self.backup_dir, f"{date_str}.jsonl")
        try:
            with open(filepath, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logger.warning("Backup write failed: %s", exc)


# ---------------------------------------------------------------------------
# fwd_from extraction helper
# ---------------------------------------------------------------------------

def _extract_forward_info(message) -> tuple:
    """
    Extract (forward_from_name, forward_from_id) from message.fwd_from.
    This is Telethon's ground-truth for forwarded messages — it contains the
    real original channel/user, not a text-match heuristic.

    Returns (None, None) when:
      - message is not forwarded at all
      - fwd_from exists but has no identifiable source (e.g. privacy-protected)
    """
    fwd = getattr(message, "fwd_from", None)
    if not fwd:
        return None, None

    # Channel / group forward
    from_id = getattr(fwd, "from_id", None)
    if from_id is not None:
        # from_id is a Peer object; extract numeric id
        channel_id = getattr(from_id, "channel_id", None) or getattr(from_id, "user_id", None)
    else:
        channel_id = None

    # Human-readable name stored by Telegram
    from_name = getattr(fwd, "from_name", None)
    # Fallback: post_author is the signature on channel posts
    if not from_name:
        from_name = getattr(fwd, "post_author", None)

    return from_name, channel_id


# ---------------------------------------------------------------------------
# Main listener
# ---------------------------------------------------------------------------

class TelegramListener:
    def __init__(self, client, db_handler, engine, group_cache, backup_writer, phone=None):
        self.client = client
        self.db = db_handler
        self.engine = engine
        self.group_cache = group_cache
        self.backup = backup_writer
        self.phone = phone
        self.queue = asyncio.Queue(maxsize=100) # Bounded queue (size 100)
        self.db_queue = asyncio.Queue() # Queue for DB batch writer
        self.worker_tasks = []
        self.db_writer_task = None
        
        self.is_fetching = True
        from concurrent.futures import ThreadPoolExecutor
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ingestion_worker")

        self.media_processor = engine.media_processor

    def register(self) -> None:
        """Attach the NewMessage handler. Safe to call multiple times (watchdog)."""
        # Remove ALL NewMessage event handlers to prevent leaks across disconnects
        for callback, event_builder in list(self.client.list_event_handlers()):
            if isinstance(event_builder, events.NewMessage):
                self.client.remove_event_handler(callback, event_builder)

        if hasattr(self, "_handler_ref"):
            try:
                self.client.remove_event_handler(self._handler_ref)
            except Exception:
                pass

        @self.client.on(events.NewMessage())
        async def _handler(event):
            if not getattr(self, "is_fetching", True):
                return
            chat_id = event.chat_id
            if self.group_cache.is_active(chat_id):
                # Backpressure warning
                qsize = self.queue.qsize()
                if qsize >= 80:
                    logger.warning("Ingestion queue near capacity (size=%d/100). Applying backpressure.", qsize)
                await self.queue.put(event)

        # Keep a reference so remove_event_handler works on reconnect
        self._handler_ref = _handler
        logger.info("NewMessage handler registered")

        # Spawn worker tasks up to the concurrency limit (e.g., 5 workers)
        self.worker_tasks = [t for t in self.worker_tasks if not t.done()]
        concurrency = 5
        to_start = concurrency - len(self.worker_tasks)
        for i in range(to_start):
            task = asyncio.create_task(self._worker(len(self.worker_tasks) + i))
            self.worker_tasks.append(task)

        # Spawn DB writer task if not running
        if self.db_writer_task is None or self.db_writer_task.done():
            self.db_writer_task = asyncio.create_task(self._db_writer())

    async def _worker(self, worker_id: int) -> None:
        """Background coroutine to process messages sequentially without blocking Telethon."""
        logger.info("TelegramListener worker %d started.", worker_id)
        while True:
            try:
                event = await self.queue.get()
                try:
                    await self._process_event(event)
                except Exception as exc:
                    logger.error("Error processing event in worker %d: %s", worker_id, exc)
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                logger.info("TelegramListener worker %d cancelled.", worker_id)
                break
            except Exception as exc:
                logger.error("Unexpected worker %d error: %s", worker_id, exc)

    async def _db_writer(self) -> None:
        """Background coroutine to batch database writes."""
        logger.info("TelegramListener DB writer started.")
        batch = []
        last_flush = asyncio.get_event_loop().time()
        
        while True:
            try:
                # Wait for an item with a timeout
                timeout = 0.5 - (asyncio.get_event_loop().time() - last_flush)
                timeout = max(0.01, timeout)
                
                try:
                    item = await asyncio.wait_for(self.db_queue.get(), timeout=timeout)
                    batch.append(item)
                    self.db_queue.task_done()
                except asyncio.TimeoutError:
                    pass
                
                # Flush if we have reached the batch limit (20) or if time has elapsed (500ms)
                now = asyncio.get_event_loop().time()
                if batch and (len(batch) >= 20 or (now - last_flush) >= 0.5):
                    await self._flush_batch(batch)
                    batch = []
                    last_flush = now
                    
            except asyncio.CancelledError:
                # Flush any remaining items before exiting
                if batch:
                    await self._flush_batch(batch)
                break
            except Exception as exc:
                logger.error("Error in DB writer loop: %s", exc, exc_info=True)

    async def _flush_batch(self, batch: list) -> None:
        logger.info("Flushing batch of %d messages to DB", len(batch))
        loop = asyncio.get_event_loop()
        try:
            inserted = await loop.run_in_executor(self.executor, self.db.insert_messages_batch, batch)
            
            # Resolve message row IDs from their hashes
            hashes = [m["hash"] for m in batch]
            hash_to_row_id = await loop.run_in_executor(self.executor, self.db.get_message_ids_by_hashes, hashes)
            
            # Process entities and semantics for each message
            for m in batch:
                row_id = hash_to_row_id.get(m["hash"])
                if row_id:
                    # Run semantic analysis (zero-shot + campaign clustering)
                    combined_sem_text = f"{m.get('text', '')}\n{m.get('ocr_text', '')}".strip()
                    await loop.run_in_executor(
                        self.executor,
                        self.engine.semantic_processor.process_message_semantics,
                        row_id,
                        combined_sem_text,
                        m["timestamp"]
                    )
                    
                    if m.get("entities"):
                        # Save entities and retrieve crypto wallets to enrich
                        crypto_to_enrich = await loop.run_in_executor(
                            self.executor,
                            self.db.save_message_entities,
                            row_id,
                            m["entities"],
                            m["timestamp"]
                        )
                        # Enqueue crypto addresses for background lookup
                        for saved_ent in crypto_to_enrich:
                            self.engine.wallet_enricher.enqueue_address(
                                saved_ent["id"],
                                saved_ent["value"],
                                saved_ent["type"],
                                saved_ent["is_sanctioned"]
                            )

                    # Run threat risk scoring and updates
                    m_db = await loop.run_in_executor(self.executor, self.db.get_message_by_row_id, row_id)
                    if m_db:
                        from src.processing.scoring_service import calculate_risk_score, dispatch_alerts
                        score = calculate_risk_score(m_db)
                        # Save score to DB
                        await loop.run_in_executor(self.executor, self.db.update_message_risk_score, row_id, score)
                        # Emit live event to connected browsers (non-blocking)
                        try:
                            from src.dashboard.app import socketio as _sio
                            _sio.emit("new_message", {
                                "id":               row_id,
                                "message_id":       m.get("message_id"),
                                "group_name":       m.get("group_name", ""),
                                "sender_name":      m.get("sender_name", ""),
                                "sender_id":        m.get("sender_id"),
                                "text":             (m.get("text") or "")[:300],
                                "timestamp":        m.get("timestamp", ""),
                                "is_matched":       int(bool(m.get("is_matched"))),
                                "matched_keyword":  m.get("matched_keyword"),
                                "threat_category":  m.get("threat_category"),
                                "risk_score":       round(score, 1),
                                "language":         m.get("language", ""),
                            })
                        except Exception:
                            pass  # Never let SocketIO errors break ingestion

                        # Update sender profile
                        if m.get("sender_name"):
                            await loop.run_in_executor(
                                self.executor,
                                self.db.update_sender_profile,
                                m["sender_name"],
                                m.get("sender_phone"),
                                score,
                                m["timestamp"]
                            )
                        # Dispatch alerts
                        await loop.run_in_executor(self.executor, dispatch_alerts, m_db, score, self.db)

                if m.get("is_matched"):
                    logger.info(
                        "MATCH [%s] kw='%s' score=%.0f | %s...",
                        m["group_name"], m["matched_keyword"],
                        m["fuzzy_score"], m["text"][:80],
                    )
        except Exception as exc:
            logger.error("Failed to flush batch of %d messages: %s", len(batch), exc)

    async def _process_event(self, event) -> None:
        try:
            chat_id = event.chat_id

            message = event.message
            chat   = await event.get_chat()
            sender = await event.get_sender()

            # Metadata
            group_name   = getattr(chat, "title", str(chat_id))
            sender_name  = ""
            sender_id    = None
            if sender:
                sender_name = (getattr(sender, "first_name", "") or "").strip()
                ln = getattr(sender, "last_name", "") or ""
                if ln:
                    sender_name = f"{sender_name} {ln}".strip()
                sender_id = str(sender.id) if hasattr(sender, "id") else None
            sender_phone = getattr(sender, "phone", None)
            text         = (message.text or message.caption or "").strip()
            is_forwarded = 1 if message.forward else 0
            timestamp    = message.date.astimezone(timezone.utc).isoformat()

            # Ground-truth forward source (fwd_from) — more reliable than text heuristics
            forward_from_name, forward_from_id = _extract_forward_info(message)

            raw = {
                "message_id":       message.id,
                "group_id":         chat_id,
                "group_name":       group_name,
                "sender_name":      sender_name,
                "sender_phone":     sender_phone,
                "sender_id":        sender_id,
                "text":             text,
                "is_forwarded":     is_forwarded,
                "forward_from_name": forward_from_name,
                "forward_from_id":  forward_from_id,
                "timestamp":        timestamp,
                "fetched_by":       self.phone,
            }

            loop = asyncio.get_event_loop()
            
            # Download and process image media if present
            media_path = None
            ocr_text = ""
            phash = None
            qr_codes = []
            
            if message.photo:
                os.makedirs("data/media", exist_ok=True)
                filename = f"img_{chat_id}_{message.id}.jpg"
                target_path = os.path.join("data/media", filename)
                try:
                    downloaded_file = await self.client.download_media(message.photo, target_path)
                    if downloaded_file:
                        media_path = downloaded_file.replace("\\", "/")
                        
                        # Process image in the background thread executor
                        media_res = await loop.run_in_executor(
                            self.executor,
                            self.media_processor.process_image,
                            media_path
                        )
                        ocr_text = media_res.get("ocr_text", "")
                        phash = media_res.get("phash")
                        qr_codes = media_res.get("qr_codes", [])
                        
                        # Periodically trigger cleanup to prevent disk bloat
                        await loop.run_in_executor(
                            self.executor,
                            self.media_processor.cleanup_media
                        )
                except Exception as exc:
                    logger.error("Failed to download or process media: %s", exc)

            # Combine OCR text with raw text for keywords & entities processing
            raw_nlp = raw.copy()
            if ocr_text:
                raw_nlp["text"] = f"{text}\n[OCR: {ocr_text}]"

            enriched = await loop.run_in_executor(self.executor, self.engine.process, raw_nlp)
            if enriched is None:
                return   # duplicate

            # Restore original raw message text and append media properties
            enriched["text"] = text
            enriched["media_path"] = media_path
            enriched["ocr_text"] = ocr_text
            enriched["phash"] = phash
            enriched["qr_codes"] = qr_codes

            # Mark seen immediately in Deduplicator to avoid other concurrent workers reprocessing the same message
            await loop.run_in_executor(self.executor, self.engine.mark_seen, enriched["hash"])
            # Write to backup
            await loop.run_in_executor(self.executor, self.backup.write, enriched)
            # Queue for database write
            await self.db_queue.put(enriched)

        # --- Specific, ordered exception handling ----------------------------
        except KeyboardInterrupt:
            raise                              # never swallow — let watchdog exit

        except FloodWaitError as exc:
            logger.warning("FloodWait in handler: sleeping %ds", exc.seconds)
            await asyncio.sleep(exc.seconds)

        except (ChatForbiddenError, ChannelPrivateError) as exc:
            logger.error("Access denied: %s", exc)

        except RPCError as exc:
            logger.error("Telegram RPC error in handler: %s", exc)

        except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
            logger.warning("Network error in handler (will auto-recover): %s", exc)

        except Exception as exc:
            logger.exception("Unhandled error in message handler: %s", exc)
