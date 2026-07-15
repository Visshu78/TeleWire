"""
src/ingestion/client.py
────────────────────────────────────────────────────────────
Telethon client setup and dialog sync.

• Reads credentials from .env (API_ID, API_HASH, PHONE)
• Persists session to <session_name>.session so subsequent runs
  are fully automatic (no OTP re-entry)
• get_all_dialogs() pulls every group/channel the account is in
  and upserts them into the groups table
────────────────────────────────────────────────────────────
"""

import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat

load_dotenv()
logger = logging.getLogger(__name__)


def build_client(session_name: str = "telegram_session", api_id: int = None, api_hash: str = None) -> TelegramClient:
    api_id = api_id or os.environ.get("API_ID")
    api_hash = api_hash or os.environ.get("API_HASH")
    if not api_id or not api_hash:
        raise EnvironmentError(
            "API_ID and API_HASH must be set in your .env file or provided parameters. "
            "Get them from https://my.telegram.org"
        )
    return TelegramClient(session_name, int(api_id), api_hash)


async def start_client(client: TelegramClient) -> None:
    """Authenticate — interactive OTP on first run, silent thereafter."""
    phone = os.environ.get("PHONE")
    if not phone:
        raise EnvironmentError("PHONE must be set in your .env file (e.g. +1234567890)")
    await client.start(phone=phone)
    me = await client.get_me()
    logger.info("Logged in as %s (id=%s)", me.first_name, me.id)


async def sync_dialogs(client: TelegramClient, db_handler) -> int:
    """
    Pull all joined groups/channels via get_dialogs() and upsert them
    into the groups table.  Returns the count of dialogs processed.
    """
    logger.info("Syncing dialogs …")
    count = 0
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        # Only groups and channels — skip DMs and bots
        if not isinstance(entity, (Channel, Chat)):
            continue
        group_type = "channel" if isinstance(entity, Channel) and entity.broadcast else "group"
        member_count = getattr(entity, "participants_count", 0) or 0
        try:
            db_handler.upsert_group(
                group_id=dialog.id,
                group_name=dialog.name or str(dialog.id),
                group_type=group_type,
                member_count=member_count,
            )
            count += 1
        except Exception as exc:
            logger.warning("Could not upsert group %s: %s", dialog.name, exc)

    logger.info("Dialog sync complete — %d groups/channels stored", count)
    return count
