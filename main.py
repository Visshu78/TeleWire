"""
main.py
-------------------------------------------------------------
Entry point. Fixes in this version vs previous:

  1. Gap backfill  -- on every reconnect, for each active group,
     fetches messages sent since last_message_at via Telethon history API
     and runs them through the full processing pipeline.

  2. Specific exceptions -- watchdog catches only transport-level errors
     (ConnectionError, OSError, asyncio.TimeoutError, RPCError).
     KeyboardInterrupt is explicitly re-raised at every catch site.

  3. FloodWait during reconnect -- if Telegram rate-limits the re-auth,
     the watchdog sleeps exc.seconds instead of its own backoff timer.

  4. Pipeline events -- disconnect / reconnect / backfill rows written to
     pipeline_events table so the dashboard can show health stats.
-------------------------------------------------------------
"""

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(path: str = "config/config.yaml") -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for noisy in ("telethon", "aiohttp", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def run_flask(app, host: str, port: int) -> None:
    from src.dashboard.app import socketio
    logging.getLogger("dashboard").info("Dashboard -> http://%s:%d", host, port)
    socketio.run(app, host=host, port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)


# ---------------------------------------------------------------------------
# Gap backfill
# ---------------------------------------------------------------------------

async def backfill_gap(client, db, engine, backup, log) -> int:
    """
    For every active group, fetch up to `backfill_limit` messages sent
    after last_message_at (the timestamp of the last stored message).

    Uses client.get_messages(entity, limit=N, offset_date=dt, reverse=True)
    so we get oldest-first and process in order.

    Returns total messages backfilled across all groups.
    """
    from telethon.errors import FloodWaitError, RPCError

    total = 0
    groups = db.get_active_groups()
    backfill_limit = 200                   # messages per group per gap

    for grp in groups:
        group_id   = grp["group_id"]
        group_name = grp["group_name"] or str(group_id)
        last_ts    = grp.get("last_message_at")
        last_id    = grp.get("last_message_id")

        if not last_ts and not last_id:
            log.debug("Backfill: no anchor for %s, skipping", group_name)
            continue

        kwargs = {
            "limit": backfill_limit,
            "reverse": True,
        }

        anchor_dt = None
        if last_id:
            log.info("Backfill: fetching up to %d msgs from [%s] strictly after id %d",
                     backfill_limit, group_name, last_id)
            kwargs["min_id"] = last_id
        else:
            try:
                anchor_dt = datetime.fromisoformat(last_ts)
            except ValueError:
                log.warning("Backfill: bad timestamp '%s' for %s", last_ts, group_name)
                continue
            log.info("Backfill: fetching up to %d msgs from [%s] after %s",
                     backfill_limit, group_name, last_ts[:19])
            kwargs["offset_date"] = anchor_dt

        try:
            messages = await client.get_messages(group_id, **kwargs)
        except FloodWaitError as exc:
            log.warning("Backfill FloodWait for %s: sleeping %ds", group_name, exc.seconds)
            await asyncio.sleep(exc.seconds)
            continue
        except (ConnectionError, OSError, asyncio.TimeoutError, RPCError) as exc:
            log.error("Backfill network error for %s: %s", group_name, exc)
            continue
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log.error("Backfill unexpected error for %s: %s", group_name, exc)
            continue

        group_batch = []
        for msg in messages:
            # Skip messages at or before the anchor if using offset_date
            if not last_id and anchor_dt and msg.date <= anchor_dt:
                continue
            if not msg.text and not msg.caption and not msg.photo:
                continue

            from src.ingestion.listener import _extract_forward_info
            forward_from_name, forward_from_id = _extract_forward_info(msg)

            raw = {
                "message_id":        msg.id,
                "group_id":          group_id,
                "group_name":        group_name,
                "sender_name":       "",
                "sender_phone":      None,
                "text":              (msg.text or msg.caption or "").strip(),
                "is_forwarded":      1 if msg.forward else 0,
                "forward_from_name": forward_from_name,
                "forward_from_id":   forward_from_id,
                "timestamp":         msg.date.astimezone(timezone.utc).isoformat(),
            }

            # Download and process image media if present
            media_path = None
            ocr_text = ""
            phash = None
            qr_codes = []
            if msg.photo:
                os.makedirs("data/media", exist_ok=True)
                filename = f"img_{group_id}_{msg.id}.jpg"
                target_path = os.path.join("data/media", filename)
                try:
                    downloaded_file = await client.download_media(msg.photo, target_path)
                    if downloaded_file:
                        media_path = downloaded_file.replace("\\", "/")
                        media_res = engine.media_processor.process_image(media_path)
                        ocr_text = media_res.get("ocr_text", "")
                        phash = media_res.get("phash")
                        qr_codes = media_res.get("qr_codes", [])
                except Exception as exc:
                    log.error("Failed to download or process backfill media: %s", exc)

            # Combine OCR text with raw text for keywords & entities processing
            raw_nlp = raw.copy()
            if ocr_text:
                raw_nlp["text"] = f"{raw_nlp['text']}\n[OCR: {ocr_text}]"

            enriched = engine.process(raw_nlp)
            if enriched is None:
                continue              # duplicate

            # Restore original text and append media info
            enriched["text"] = raw["text"]
            enriched["media_path"] = media_path
            enriched["ocr_text"] = ocr_text
            enriched["phash"] = phash
            enriched["qr_codes"] = qr_codes
            group_batch.append(enriched)

        if group_batch:
            inserted_count = db.insert_messages_batch(group_batch)
            hash_to_row_id = db.get_message_ids_by_hashes([m["hash"] for m in group_batch])
            for enriched in group_batch:
                engine.mark_seen(enriched["hash"])
                backup.write(enriched)
                
                row_id = hash_to_row_id.get(enriched["hash"])
                if row_id:
                    # Run semantic analysis (zero-shot + campaign clustering)
                    combined_sem_text = f"{enriched.get('text', '')}\n{enriched.get('ocr_text', '')}".strip()
                    engine.semantic_processor.process_message_semantics(
                        row_id,
                        combined_sem_text,
                        enriched["timestamp"]
                    )
                    
                    if enriched.get("entities"):
                        crypto_to_enrich = db.save_message_entities(row_id, enriched["entities"], enriched["timestamp"])
                        for saved_ent in crypto_to_enrich:
                            engine.wallet_enricher.enqueue_address(
                                saved_ent["id"],
                                saved_ent["value"],
                                saved_ent["type"],
                                saved_ent["is_sanctioned"]
                            )

                    # Run threat risk scoring and updates
                    m_db = db.get_message_by_row_id(row_id)
                    if m_db:
                        from src.processing.scoring_service import calculate_risk_score, dispatch_alerts
                        score = calculate_risk_score(m_db)
                        db.update_message_risk_score(row_id, score)
                        if enriched.get("sender_name"):
                            db.update_sender_profile(
                                enriched["sender_name"],
                                enriched.get("sender_phone"),
                                score,
                                enriched["timestamp"]
                            )
                        # Dispatch alerts
                        dispatch_alerts(m_db, score, db)
            total += len(group_batch)
            log.info("Backfill: batch inserted %d messages (total new=%d) for [%s]", inserted_count, len(group_batch), group_name)

    return total


# ---------------------------------------------------------------------------
# Watchdog reconnect loop
# ---------------------------------------------------------------------------

async def watchdog_loop(client, db, engine, group_cache, backup, config: dict, listener) -> None:
    """
    Resilient listener loop.

    Disconnect behaviour:
      1. Logs WARNING + records pipeline_events 'disconnect' row with timestamp.
      2. Exponential backoff: 5 -> 10 -> 20 -> ... capped at 120 s.
         Exception: FloodWaitError during re-auth uses exc.seconds directly.
      3. Re-authenticates silently from .session file.
      4. Calls backfill_gap() to recover messages sent while offline.
      5. Re-registers handler, resumes, resets backoff, closes event row.

    Exception hierarchy (specific, not bare Exception):
      KeyboardInterrupt  -> always re-raised immediately
      FloodWaitError     -> sleep exc.seconds (Telegram-mandated, not our backoff)
      ConnectionError / OSError / asyncio.TimeoutError -> transport errors
      RPCError           -> Telegram protocol errors
      Exception          -> last-resort catch with full traceback
    """
    from telethon.errors import FloodWaitError, RPCError
    from src.ingestion.client import start_client, sync_dialogs

    log = logging.getLogger("watchdog")
    backoff     = 5
    max_backoff = 120
    attempt     = 0

    while True:
        attempt += 1
        disconnect_event_id = None
        disconnect_start    = None

        try:
            log.info("Watchdog [#%d]: listening ...", attempt)
            listener.register()
            await client.run_until_disconnected()
            # Clean disconnect (server closed connection)
            disconnect_start = datetime.now(timezone.utc).isoformat()
            log.warning("Watchdog: disconnected at %s -- reconnecting in %ds ...",
                        disconnect_start[:19], backoff)

        except KeyboardInterrupt:
            log.info("Watchdog: KeyboardInterrupt -- shutting down.")
            raise

        except FloodWaitError as exc:
            # run_until_disconnected itself threw FloodWait -- respect it
            log.warning("Watchdog: FloodWait %ds (from run loop)", exc.seconds)
            await asyncio.sleep(exc.seconds)
            continue                           # skip normal backoff

        except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
            disconnect_start = datetime.now(timezone.utc).isoformat()
            log.error("Watchdog: network error: %s -- reconnecting in %ds ...", exc, backoff)

        except RPCError as exc:
            disconnect_start = datetime.now(timezone.utc).isoformat()
            log.error("Watchdog: RPC error: %s -- reconnecting in %ds ...", exc, backoff)

        except Exception as exc:
            disconnect_start = datetime.now(timezone.utc).isoformat()
            log.exception("Watchdog: unexpected error: %s -- reconnecting in %ds ...", exc, backoff)

        # Record disconnect event
        if disconnect_start:
            try:
                disconnect_event_id = db.log_event(
                    "disconnect", disconnect_start,
                    details=f"attempt={attempt}"
                )
            except Exception:
                pass   # DB logging must never crash the loop

        # --- Backoff ---------------------------------------------------------
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)

        # --- Reconnect -------------------------------------------------------
        reconnect_ok = False
        try:
            if not client.is_connected():
                await start_client(client)      # silent if .session exists
            synced = await sync_dialogs(client, db)
            log.info("Watchdog: reconnected -- %d groups re-synced.", synced)
            reconnect_ok = True
            backoff = 5                          # reset on success

        except KeyboardInterrupt:
            raise

        except FloodWaitError as exc:
            # Telegram rate-limited the re-auth itself
            log.warning("Watchdog: FloodWait %ds during reconnect -- waiting ...", exc.seconds)
            await asyncio.sleep(exc.seconds)
            # Don't reset backoff; let the next iteration retry

        except (ConnectionError, OSError, asyncio.TimeoutError, RPCError) as exc:
            log.error("Watchdog: reconnect failed: %s -- retry in %ds", exc, backoff)

        except Exception as exc:
            log.exception("Watchdog: reconnect unexpected: %s -- retry in %ds", exc, backoff)

        # --- Gap backfill (only when reconnect succeeded) --------------------
        if reconnect_ok:
            reconnect_ts = datetime.now(timezone.utc).isoformat()
            try:
                backfilled = await backfill_gap(client, db, engine, backup, log)
                log.info("Watchdog: backfilled %d missed messages.", backfilled)
                # Record reconnect + close disconnect event
                db.log_event(
                    "reconnect", reconnect_ts,
                    ended_at=reconnect_ts,
                    duration_seconds=0,
                    details=f"backfilled={backfilled}",
                )
                if disconnect_event_id and disconnect_start:
                    try:
                        duration = (
                            datetime.fromisoformat(reconnect_ts) -
                            datetime.fromisoformat(disconnect_start)
                        ).total_seconds()
                        db.close_event(disconnect_event_id, reconnect_ts,
                                       duration, f"backfilled={backfilled}")
                    except Exception:
                        pass
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                log.error("Watchdog: backfill error: %s", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    config = load_config()
    setup_logging(config.get("log_level", "INFO"))
    log = logging.getLogger("main")
    log.info("TeleWire Threat Intelligence Pipeline starting")

    # Storage
    from src.storage.database import DatabaseHandler, init_db
    db_path = config.get("db_path", "data/telegram_intel.db")
    init_db(db_path)
    db = DatabaseHandler(db_path)
    db.log_event("startup", datetime.now(timezone.utc).isoformat())

    seeded = db.seed_keywords_from_file("config/keywords.txt")
    if seeded:
        log.info("Seeded %d keywords", seeded)

    # Processing engine
    from src.processing import ProcessingEngine
    engine = ProcessingEngine(db, config)
    log.info("ProcessingEngine ready (threshold=%d)", config.get("fuzzy_threshold", 85))

    # Initialize PipelineManager
    from src.ingestion.pipeline_manager import PipelineManager
    pipeline_manager = PipelineManager(db, engine, config)

    # Migrate environment variables configuration to DB accounts on first run
    # Migrate environment variables configuration to DB accounts on first run
    accounts = db.get_telegram_accounts()
    if not accounts:
        phone = os.environ.get("PHONE")
        api_id = os.environ.get("API_ID")
        api_hash = os.environ.get("API_HASH")
        if phone and api_id and api_hash:
            log.info("Migrating environment variables default single account to database")
            db.upsert_telegram_account(
                phone,
                int(api_id),
                api_hash,
                "data/telegram_session",
                is_active=1,
                status="connected"
            )
            accounts = db.get_telegram_accounts()

    # Backfill historical messages fetched_by column that is NULL
    if accounts:
        primary_phone = accounts[0]["phone"]
        try:
            from src.storage.database import get_db
            with get_db(db_path) as conn:
                cur = conn.execute("UPDATE messages SET fetched_by = ? WHERE fetched_by IS NULL", (primary_phone,))
                if cur.rowcount > 0:
                    log.info("Backfilled %d historical messages fetched_by to primary account %s", cur.rowcount, primary_phone)
        except Exception as e:
            log.warning("Could not backfill historical messages fetched_by column: %s", e)
    await pipeline_manager.start_all()

    # Group Discovery Scanner (background asyncio task)
    discovery_task = None
    try:
        from src.ingestion.discovery_service import GroupDiscoveryService
        # Use the first active client from the pipeline manager
        first_client = pipeline_manager.get_first_client()
        if first_client:
            scan_interval = config.get("discovery_scan_interval", 300)
            discovery_svc = GroupDiscoveryService(first_client, db, scan_interval)
            discovery_task = asyncio.create_task(discovery_svc.run())
            log.info("GroupDiscoveryService started (interval=%ds)", scan_interval)
        else:
            log.warning("GroupDiscoveryService: no active Telethon client, scanner skipped.")
    except Exception as exc:
        log.warning("GroupDiscoveryService failed to start: %s", exc)

    # Flask dashboard (daemon thread)
    from src.dashboard.app import create_app
    flask_app = create_app(db, pipeline_manager.group_cache, pipeline_manager)
    host = config.get("dashboard_host", "0.0.0.0")
    port = config.get("dashboard_port", 5000)
    threading.Thread(target=run_flask, args=(flask_app, host, port), daemon=True).start()
    log.info("Dashboard       -> http://localhost:%d", port)
    log.info("Keyword Manager -> streamlit run keyword_manager.py")

    # Ingestion Manager Daemon Execution Loop
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        log.info("Shutting down ...")
    finally:
        if discovery_task and not discovery_task.done():
            discovery_task.cancel()
            try:
                await discovery_task
            except asyncio.CancelledError:
                pass
        await pipeline_manager.stop_all()
        log.info("Disconnected. Bye.")



if __name__ == "__main__":
    asyncio.run(main())
