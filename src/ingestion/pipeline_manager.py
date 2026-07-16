import logging
import asyncio
import os
from telethon import TelegramClient
from src.ingestion.client import build_client, sync_dialogs
from src.ingestion.listener import TelegramListener, ActiveGroupCache, BackupWriter

logger = logging.getLogger(__name__)


class PipelineManager:
    def __init__(self, db_handler, processing_engine, config: dict):
        self.db = db_handler
        self.engine = processing_engine
        self.config = config
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None
        
        self.is_fetching = True
        self.active_clients = {}      # phone -> TelegramClient
        self.active_listeners = {}    # phone -> TelegramListener
        self.pending_otps = {}        # phone -> dict(client, phone_code_hash, api_id, api_hash)
        
        # Shared elements across all active sessions
        self.group_cache = ActiveGroupCache(self.db)
        self.backup = BackupWriter(
            backup_dir=config.get("backup_dir", "data/backup"),
            enabled=config.get("backup_enabled", True)
        )

    def get_status(self) -> dict:
        """Returns the active state of the manager and list of accounts."""
        accounts = self.db.get_telegram_accounts()
        processed = []
        for acc in accounts:
            phone = acc["phone"]
            status = acc["status"]
            if phone in self.active_clients:
                status = "connected"
            elif phone in self.pending_otps:
                status = "needs_otp"
            
            processed.append({
                "phone": phone,
                "api_id": acc["api_id"],
                "api_hash": acc["api_hash"],
                "is_active": acc["is_active"],
                "status": status
            })
            
        return {
            "is_fetching": self.is_fetching,
            "accounts": processed
        }

    async def toggle_fetching(self, enabled: bool) -> None:
        """Globally pause/resume ingestion updates from all clients."""
        self.is_fetching = enabled
        for listener in self.active_listeners.values():
            listener.is_fetching = enabled
        logger.info("Global message fetching set to: %s", enabled)

    def get_first_client(self):
        """Return the first active TelegramClient, or None if none connected."""
        for client in self.active_clients.values():
            return client
        return None

    async def start_all(self) -> None:
        """Connect all registered active accounts on startup."""
        accounts = self.db.get_telegram_accounts()
        for acc in accounts:
            if acc["is_active"] == 1:
                phone = acc["phone"]
                api_id = acc["api_id"]
                api_hash = acc["api_hash"]
                session_name = acc["session_name"]
                
                logger.info("Starting account pipeline: %s", phone)
                try:
                    client = build_client(session_name, api_id, api_hash)
                    await client.connect()
                    
                    if await client.is_user_authorized():
                        self.active_clients[phone] = client
                        self.db.update_telegram_account_status(phone, "connected")
                        
                        await sync_dialogs(client, self.db)
                        
                        listener = TelegramListener(client, self.db, self.engine, self.group_cache, self.backup, phone=phone)
                        listener.is_fetching = self.is_fetching
                        listener.register()
                        self.active_listeners[phone] = listener
                        logger.info("Pipeline listener fully initialized for: %s", phone)
                    else:
                        self.db.update_telegram_account_status(phone, "disconnected")
                        logger.warning("Session exists but user unauthorized: %s", phone)
                except Exception as exc:
                    logger.error("Failed to start account pipeline %s: %s", phone, exc)

    async def stop_all(self) -> None:
        """Disconnect and stop all listeners."""
        for phone, client in list(self.active_clients.items()):
            try:
                listener = self.active_listeners.get(phone)
                if listener:
                    for task in listener.worker_tasks:
                        task.cancel()
                    if listener.db_writer_task:
                        listener.db_writer_task.cancel()
                await client.disconnect()
                logger.info("Disconnected client for: %s", phone)
            except Exception as exc:
                logger.warning("Error disconnecting %s: %s", phone, exc)
        self.active_clients.clear()
        self.active_listeners.clear()

    async def add_account(self, phone: str, api_id: int, api_hash: str) -> dict:
        """Adds a phone number and initiates Telethon login connection."""
        if len(self.db.get_telegram_accounts()) >= 5:
            return {"status": "error", "message": "Maximum of 5 accounts is allowed."}
            
        phone_stripped = phone.replace("+", "").replace(" ", "").replace("-", "")
        session_name = f"data/telegram_session_{phone_stripped}"
        
        self.db.upsert_telegram_account(phone, api_id, api_hash, session_name, is_active=1, status="disconnected")

        try:
            client = build_client(session_name, api_id, api_hash)
            await client.connect()

            if await client.is_user_authorized():
                self.active_clients[phone] = client
                self.db.update_telegram_account_status(phone, "connected")
                
                await sync_dialogs(client, self.db)
                
                listener = TelegramListener(client, self.db, self.engine, self.group_cache, self.backup, phone=phone)
                listener.is_fetching = self.is_fetching
                listener.register()
                self.active_listeners[phone] = listener
                
                return {"status": "connected"}
            else:
                sent_code = await client.send_code_request(phone)
                self.pending_otps[phone] = {
                    "client": client,
                    "phone_code_hash": sent_code.phone_code_hash,
                    "api_id": api_id,
                    "api_hash": api_hash,
                    "session_name": session_name
                }
                self.db.update_telegram_account_status(phone, "needs_otp")
                return {"status": "needs_otp"}
        except Exception as exc:
            logger.error("Failed to add account %s: %s", phone, exc)
            return {"status": "error", "message": str(exc)}

    async def verify_otp(self, phone: str, code: str) -> dict:
        """Completes authentication with the code sent to phone."""
        pending = self.pending_otps.get(phone)
        if not pending:
            return {"status": "error", "message": "No pending auth request for this number."}

        client = pending["client"]
        phone_code_hash = pending["phone_code_hash"]

        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            
            self.active_clients[phone] = client
            self.db.update_telegram_account_status(phone, "connected")
            
            await sync_dialogs(client, self.db)
            
            listener = TelegramListener(client, self.db, self.engine, self.group_cache, self.backup, phone=phone)
            listener.is_fetching = self.is_fetching
            listener.register()
            self.active_listeners[phone] = listener
            
            del self.pending_otps[phone]
            return {"status": "connected"}
        except Exception as exc:
            logger.error("OTP verification failed for %s: %s", phone, exc)
            return {"status": "error", "message": str(exc)}

    async def remove_account(self, phone: str) -> bool:
        """Removes the account from the manager and deletes session cache."""
        client = self.active_clients.get(phone)
        if client:
            try:
                listener = self.active_listeners.get(phone)
                if listener:
                    for task in listener.worker_tasks:
                        task.cancel()
                    if listener.db_writer_task:
                        listener.db_writer_task.cancel()
                await client.disconnect()
            except Exception:
                pass
            self.active_clients.pop(phone, None)
            self.active_listeners.pop(phone, None)

        self.pending_otps.pop(phone, None)
        
        acc = self.db.get_telegram_accounts()
        acc_dict = next((a for a in acc if a["phone"] == phone), None)
        if acc_dict:
            session_file = acc_dict["session_name"] + ".session"
            if os.path.exists(session_file):
                try:
                    os.remove(session_file)
                except Exception:
                    pass
                    
        return self.db.delete_telegram_account(phone)

    async def toggle_account_active(self, phone: str, is_active: int) -> dict:
        """Dynamically start or stop an individual account client based on toggle switch."""
        self.db.update_telegram_account_active(phone, is_active)
        
        if is_active == 1:
            accounts = self.db.get_telegram_accounts()
            acc = next((a for a in accounts if a["phone"] == phone), None)
            if not acc:
                return {"status": "error", "message": "Account configuration not found."}
                
            if phone in self.active_clients:
                return {"status": "connected"}
                
            try:
                client = build_client(acc["session_name"], acc["api_id"], acc["api_hash"])
                await client.connect()
                
                if await client.is_user_authorized():
                    self.active_clients[phone] = client
                    self.db.update_telegram_account_status(phone, "connected")
                    
                    await sync_dialogs(client, self.db)
                    
                    listener = TelegramListener(client, self.db, self.engine, self.group_cache, self.backup, phone=phone)
                    listener.is_fetching = self.is_fetching
                    listener.register()
                    self.active_listeners[phone] = listener
                    
                    return {"status": "connected"}
                else:
                    self.db.update_telegram_account_status(phone, "disconnected")
                    sent_code = await client.send_code_request(phone)
                    self.pending_otps[phone] = {
                        "client": client,
                        "phone_code_hash": sent_code.phone_code_hash,
                        "api_id": acc["api_id"],
                        "api_hash": acc["api_hash"],
                        "session_name": acc["session_name"]
                    }
                    self.db.update_telegram_account_status(phone, "needs_otp")
                    return {"status": "needs_otp"}
            except Exception as exc:
                logger.error("Failed to dynamically activate account %s: %s", phone, exc)
                return {"status": "error", "message": str(exc)}
        else:
            client = self.active_clients.get(phone)
            if client:
                try:
                    listener = self.active_listeners.get(phone)
                    if listener:
                        for task in listener.worker_tasks:
                            task.cancel()
                        if listener.db_writer_task:
                            listener.db_writer_task.cancel()
                    await client.disconnect()
                except Exception:
                    pass
                self.active_clients.pop(phone, None)
                self.active_listeners.pop(phone, None)

            self.pending_otps.pop(phone, None)
            self.db.update_telegram_account_status(phone, "disconnected")
            return {"status": "disconnected"}

    async def join_group(self, link: str, phone: str = None) -> dict:
        """Join a group/channel using an active client, and upsert it in monitored groups."""
        if not self.active_clients:
            return {"status": "error", "message": "No active Telegram accounts are connected. Please connect at least one account."}
            
        client = None
        if phone:
            client = self.active_clients.get(phone)
        if not client:
            client = list(self.active_clients.values())[0]
            
        import re
        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.tl.functions.messages import ImportChatInviteRequest
        from telethon.errors import UserAlreadyParticipantError
        from telethon.tl.types import Channel, Chat
        
        link = link.strip()
        entity = None
        private_match = None
        
        # 1. Try private invite link
        private_match = re.search(r'(?:t\.me|telegram\.me)/(?:joinchat/|\+)([a-zA-Z0-9_\-]+)', link)
        if private_match:
            invite_hash = private_match.group(1)
            try:
                updates = await client(ImportChatInviteRequest(invite_hash))
                if hasattr(updates, 'chats') and updates.chats:
                    entity = updates.chats[0]
            except UserAlreadyParticipantError:
                pass
            except Exception as e:
                return {"status": "error", "message": f"Failed to join private invite: {str(e)}"}
                
        # 2. Try public link or username
        if not entity:
            username_match = re.search(r'(?:t\.me|telegram\.me|telegram\.dog)/([a-zA-Z0-9_]{4,})', link)
            target = username_match.group(1) if username_match else link.lstrip('@')
            
            try:
                entity = await client.get_entity(target)
                if isinstance(entity, (Channel, Chat)):
                    await client(JoinChannelRequest(entity))
            except Exception as e:
                if not private_match:
                    return {"status": "error", "message": f"Failed to join public group: {str(e)}"}
                    
        # Fallback if already participant in private chat
        if not entity and private_match:
            await sync_dialogs(client, self.db)
            return {"status": "success", "message": "Already a participant. Dialogs synced."}

        if not entity or not isinstance(entity, (Channel, Chat)):
            return {"status": "error", "message": "Could not resolve a valid group or channel from input."}
            
        group_type = "channel" if isinstance(entity, Channel) and entity.broadcast else "group"
        member_count = getattr(entity, "participants_count", 0) or 0
        
        self.db.upsert_group(
            group_id=entity.id,
            group_name=getattr(entity, 'title', '') or str(entity.id),
            group_type=group_type,
            member_count=member_count
        )
        
        self.group_cache.set_active(entity.id, 1)
        
        return {
            "status": "success",
            "group_id": entity.id,
            "group_name": getattr(entity, 'title', '') or str(entity.id),
            "group_type": group_type,
            "member_count": member_count
        }

    async def search_public_groups(self, query: str, phone: str = None) -> list:
        """Search public groups/channels using an active client."""
        if not self.active_clients:
            return []
            
        client = None
        if phone:
            client = self.active_clients.get(phone)
        if not client:
            client = list(self.active_clients.values())[0]
            
        from telethon.tl.functions.contacts import SearchRequest
        from telethon.tl.types import Channel, Chat
        
        try:
            result = await client(SearchRequest(q=query, limit=20))
            chats = []
            for chat in result.chats:
                if isinstance(chat, (Channel, Chat)):
                    group_type = "channel" if isinstance(chat, Channel) and chat.broadcast else "group"
                    chats.append({
                        "group_id": chat.id,
                        "group_name": getattr(chat, 'title', '') or str(chat.id),
                        "username": getattr(chat, 'username', '') or '',
                        "group_type": group_type,
                        "member_count": getattr(chat, 'participants_count', 0) or 0
                    })
            return chats
        except Exception as e:
            logger.error("Failed to search public groups for query '%s': %s", query, e)
            return []

